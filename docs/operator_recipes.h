#pragma once

// 从已通过库内检验的因子中抽出的可复用算子核心。
// 这些类不是 FeedIndicator 子类：请在 onEndBook() 里调用 update()，
// 并在 onStarted() 里重建或清空对应状态。

#include <algorithm>
#include <array>
#include <cmath>

namespace operator_recipes {

// ---------------------------------------------------------------------------
// 通用滚动分位窗口
// ---------------------------------------------------------------------------

template <size_t Win>
struct RollingRank {
    static_assert(Win > 1, "Win 必须大于 1");

    void push(double x) {
        data[idx] = x;
        idx = (idx + 1) % Win;
        if (count < Win) ++count;
    }

    // 平均秩版本的分位值，范围为 [0, 1]。
    // 这是状态归一化时默认使用的 rank，能减少重复值造成的跳变。
    double rank(double x) const {
        size_t below = 0;
        size_t equal = 0;
        for (size_t i = 0; i < count; ++i) {
            if (data[i] < x) ++below;
            else if (data[i] == x) ++equal;
        }
        return (double(below) + 0.5 * double(equal)) / double(count);
    }

    // P(x <= value)，即小于等于当前值的比例。
    // AnchoredPhase 用这个口径复现已验证过的“超过 K 分位才算异常跳变”规则。
    double rank_le(double x) const {
        size_t le = 0;
        for (size_t i = 0; i < count; ++i) {
            if (data[i] <= x) ++le;
        }
        return double(le) / double(count);
    }

    bool full() const { return count >= Win; }

    std::array<double, Win> data{};
    size_t idx = 0;
    size_t count = 0;
};

// ---------------------------------------------------------------------------
// 1. TerminalStateEntryInnovation
//
// 回答的问题：在当前终态相同的样本中，进入这个状态之前的位移
// 是否仍然携带额外方向信息？
//
// state 通常取最优档盘口失衡：
//     imb = (bid0 - ask0) / (bid0 + ask0)
//
// UseResidual=true  -> 使用残差 surprise，冗余更低，@1 因果口径更稳。
// UseResidual=false -> 使用原始入态位移，对应当前最强的 bucket 因子版本。
// ---------------------------------------------------------------------------

template <size_t Win = 500, class AgreementBoost = DoubleCreator<2, 0>,
          bool UseResidual = true>
class TerminalStateEntryInnovation {
public:
    struct Result {
        double level_rank = 0.5;
        double delta = 0.0;
        double mean_delta = 0.0;
        double residual = 0.0;
        double scale_rank = 0.5;
        double innovation = 0.0;
        bool agreement = false;
    };

    bool ready() const {
        return state_rank.full() && scale_rank.full()
            && delta_count >= Win && has_prev;
    }

    Result update(double state) {
        const double delta = has_prev ? state - prev_state : 0.0;
        prev_state = state;
        has_prev = true;

        // 维护 delta 的滚动均值。原始 delta 会和失衡水平自相关；
        // residual = delta - mean(delta) 用于抽出真正的突发成分。
        if (delta_count < Win) {
            delta_ring[delta_idx] = delta;
            delta_sum += delta;
            ++delta_count;
        } else {
            delta_sum += delta - delta_ring[delta_idx];
            delta_ring[delta_idx] = delta;
        }
        delta_idx = (delta_idx + 1) % Win;

        const double mean_delta = delta_sum / double(delta_count);
        const double residual = delta - mean_delta;
        const double scale = UseResidual ? residual : delta;

        state_rank.push(state);
        scale_rank.push(std::fabs(scale));

        Result r;
        r.level_rank = state_rank.rank(state);
        r.delta = delta;
        r.mean_delta = mean_delta;
        r.residual = residual;
        r.scale_rank = scale_rank.rank(std::fabs(scale));

        const int scale_side = scale > 0.0 ? 1 : -1;
        const int level_side = r.level_rank >= 0.5 ? 1 : -1;
        r.agreement = scale_side == level_side;

        // 带符号的幅度分位是入态新息的核心。若入态方向与当前盘口压力方向
        // 一致，则放大；不一致时不丢弃，只保留原幅度。
        const double sign = scale > 0.0 ? 1.0 : -1.0;
        const double gain = r.agreement ? AgreementBoost::value : 1.0;
        r.innovation = sign * r.scale_rank * gain;
        return r;
    }

private:
    RollingRank<Win> state_rank;
    RollingRank<Win> scale_rank;
    std::array<double, Win> delta_ring{};
    size_t delta_idx = 0;
    size_t delta_count = 0;
    double delta_sum = 0.0;
    double prev_state = 0.0;
    bool has_prev = false;
};

// ---------------------------------------------------------------------------
// 2. ConditionalBucketComposition
//
// 已验证最强的组合结构里，载体变量不是固定符号。
// 它的符号由终态 bucket 决定。通过检验的因子中：
// 载体是买侧深档熵，条件状态是最优档失衡分位。
// ---------------------------------------------------------------------------

struct ConditionalBucketComposition {
    // carrier_rank：方向载体分位，例如深档熵分位。
    // state_rank：条件状态分位，例如最优档失衡分位。
    // entry_innovation：TerminalStateEntryInnovation 的输出。
    static double combine(double carrier_rank, double state_rank,
                          double entry_innovation, double carrier_gain = 4.0) {
        int bucket = int(std::floor(state_rank * 5.0));
        bucket = std::max(0, std::min(4, bucket));

        // DepthEntropyBucketEntryAdd 实测得到的符号曲线：
        // 卖压 bucket 为正，进入买压 bucket 后权重衰减并翻转。
        static constexpr double weights[5] = {1.0, 0.4, 0.0, -0.2, -0.3};
        const double carrier_term =
            (carrier_rank - 0.5) * weights[bucket] * carrier_gain;

        // 使用加法组合，便于评估阶段分别归因两项贡献；
        // 也避免用硬门控把入态新息直接遮蔽掉。
        return carrier_term + entry_innovation;
    }
};

// ---------------------------------------------------------------------------
// 3. AnchoredPhaseOperator
//
// 一个状态水平的可读性，取决于距离上一次异常跳变过去了多久。
// 锚点定义为 |state - prev(state)| 超过自身历史 K 分位；
// tau 表示距离最近一个锚点已经过去了多少个观测。
//
// Continuous=true  -> 连续相位 × 中心化水平；更平滑，库内冗余 R2_X 很低。
// Continuous=false -> fresh/normal 二态门控；短 horizon 上更强。
// ---------------------------------------------------------------------------

template <size_t Win = 500, class KThresh = DoubleCreator<98, -2>,
          size_t TFresh = 15, class FreshCoef = DoubleCreator<-1, 0>,
          size_t PhaseC = 20, size_t TauCap = 200,
          class Gain = DoubleCreator<4, 0>, bool Continuous = true>
class AnchoredPhaseOperator {
public:
    struct Result {
        double level_rank = 0.5;
        size_t tau = 0;
        double phase = 0.0;
        double output = 0.0;
        bool anchored = false;
        bool ready = false;
    };

    Result update(double state) {
        if (!has_prev) {
            prev_state = state;
            has_prev = true;
            return {};
        }

        const double jump = std::fabs(state - prev_state);
        prev_state = state;

        jump_rank.push(jump);
        state_rank.push(state);

        Result r;
        r.ready = jump_rank.full() && state_rank.full();
        if (!r.ready) {
            tau = std::min(tau + 1, TauCap);
            return r;
        }

        // rank_le 复现已验证规则：只有极端尾部跳变才重置 tau。
        const double jump_pct = jump_rank.rank_le(jump);
        r.anchored = jump_pct > KThresh::value;
        if (r.anchored) {
            tau = 0;
        } else {
            tau = std::min(tau + 1, TauCap);
        }

        r.level_rank = state_rank.rank(state);
        r.tau = tau;
        const double centered_level = r.level_rank - 0.5;

        if (Continuous) {
            // 新锚点附近 phase=-0.5，随着时间消化逐渐趋向 +0.5。
            // 含义是：刚跳变后反向读水平，冷却后恢复正常方向。
            r.phase = double(tau) / double(tau + PhaseC) - 0.5;
            r.output = r.phase * centered_level * Gain::value;
        } else {
            // 二态耗散门控。FreshCoef=-1 表示 fresh 阶段反向使用当前水平。
            const double gate = tau < TFresh ? FreshCoef::value : 1.0;
            r.phase = gate;
            r.output = gate * centered_level * Gain::value;
        }
        return r;
    }

private:
    RollingRank<Win> jump_rank;
    RollingRank<Win> state_rank;
    double prev_state = 0.0;
    bool has_prev = false;
    size_t tau = 0;
};

// ---------------------------------------------------------------------------
// 4. RunLengthBellModulator
//
// 买一档量的同号变化持续越久，越偏向反转状态；但该效应主要出现在
// 活动变化中等的时候。极低和极高活动都会被压制。
// abs_activity 通常取 |持仓变化|。
// ---------------------------------------------------------------------------

template <size_t EnergyWin = 200, size_t RunWin = 500, class Gain = DoubleCreator<2, 0>>
class RunLengthBellModulator {
public:
    struct Result {
        double energy_rank = 0.5;
        double run_rank = 0.5;
        double bell = 0.0;
        double output = 0.0;
        bool ready = false;
    };

    // direction_sign：+1、0 或 -1，通常取 sign(bid_size0 - prev_bid_size0)。
    Result update(int direction_sign, double abs_activity) {
        energy_rank.push(abs_activity);

        if (direction_sign == 0) {
            run = 0;
        } else if (direction_sign == last_sign) {
            ++run;
        } else {
            run = 1;
        }
        last_sign = direction_sign;
        run_rank.push(double(run));

        Result r;
        r.ready = energy_rank.full() && run_rank.full();
        if (!r.ready) return r;

        r.energy_rank = energy_rank.rank(abs_activity);
        r.run_rank = run_rank.rank(double(run));

        // 钟形权重在中间最高，在两端趋近 0。
        // 这表达的是实测的非单调条件关系，而不是简单的“越大越好”。
        const double e = std::max(0.0, std::min(1.0, r.energy_rank));
        r.bell = std::sqrt(e * (1.0 - e));

        // 历史证据显示：游程越长，未来收益越偏负。
        // 除非新样本证明符号翻转，否则保留这里的负号。
        r.output = -r.run_rank * r.bell * Gain::value;
        return r;
    }

private:
    RollingRank<EnergyWin> energy_rank;
    RollingRank<RunWin> run_rank;
    int last_sign = 0;
    size_t run = 0;
};

// ---------------------------------------------------------------------------
// 5. IntentActionValidation
//
// 意图层使用最优档撤单流，行动层使用主动成交流。
// 核心问题是：真实成交是确认、削弱，还是反转了原来的挂单意图。
// 已测版本的期望 IC 为负；若要采用“正值代表看多”的常规口径，应对输出取反。
// ---------------------------------------------------------------------------

template <size_t Win = 500>
class IntentActionValidation {
public:
    enum class Mode {
        Multiplicative,   // 乘性版：intent * (1 + action_score)。
        PiecewiseResidual // 分段残差版：只有在背离时行动层才等权参与。
    };

    struct Result {
        double intent_imb = 0.0;
        double action_imb = 0.0;
        double intent_score = 0.0;
        double action_score = 0.0;
        double output = 0.0;
        bool ready = false;
    };

    // 传入每个 book 周期内累计的数量。意图层用 level=0 的撤单；
    // 行动层用全档成交。BUY 表示买侧撤单或主动买。
    Result update(double intent_buy, double intent_sell,
                  double action_buy, double action_sell,
                  Mode mode = Mode::PiecewiseResidual) {
        r.intent_imb = (intent_buy - intent_sell)
            / (intent_buy + intent_sell + 1.0);
        r.action_imb = (action_buy - action_sell)
            / (action_buy + action_sell + 1.0);

        intent_rank.push(r.intent_imb);
        action_rank.push(r.action_imb);

        r.ready = intent_rank.full() && action_rank.full();
        if (!r.ready) {
            r.output = 0.0;
            return r;
        }

        r.intent_score = intent_rank.rank(r.intent_imb) - 0.5;
        r.action_score = action_rank.rank(r.action_imb) - 0.5;

        if (mode == Mode::Multiplicative) {
            // 行动同向则放大意图；行动反向则削弱甚至翻转；
            // 行动中性时保留原始意图信号。
            r.output = r.intent_score * (1.0 + r.action_score);
        } else {
            // 背离时让行动层等权参与，因为行动本身可能是有效残差；
            // 一致时用交互项放大已被成交确认的意图。
            if (r.intent_score * r.action_score < 0.0) {
                r.output = 0.5 * r.intent_score + 0.5 * r.action_score;
            } else {
                r.output = r.intent_score
                    + r.intent_score * r.action_score;
            }
        }
        return r;
    }

private:
    RollingRank<Win> intent_rank;
    RollingRank<Win> action_rank;
    Result r;
};

// ---------------------------------------------------------------------------
// 6. TwoSidedEntropyAsymGate
//
// 置信度较低但有价值的盘口形状修复：比较买侧深档熵与卖侧深档熵分位。
// 若某一侧分布异常重构，则修正熵载体的方向符号。
// ---------------------------------------------------------------------------

struct TwoSidedEntropyAsymGate {
    static double combine(double bid_entropy_rank, double ask_entropy_rank,
                          double imb_rank, double gain = 4.0,
                          double asym_threshold = 0.15,
                          double asym_correction = 0.5) {
        int bucket = int(std::floor(imb_rank * 5.0));
        bucket = std::max(0, std::min(4, bucket));
        static constexpr double weights[5] = {1.0, 0.4, 0.0, -0.2, -0.3};

        const double delta_rank = bid_entropy_rank - ask_entropy_rank;
        double correction = 0.0;
        if (delta_rank > asym_threshold) {
            correction = -asym_correction;
        } else if (delta_rank < -asym_threshold) {
            correction = +asym_correction;
        }

        const double effective_sign = weights[bucket] + correction;
        return (bid_entropy_rank - 0.5) * effective_sign * gain;
    }
};

} // namespace operator_recipes
