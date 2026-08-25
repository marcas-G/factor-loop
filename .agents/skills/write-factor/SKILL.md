---
name: write-factor
description: Generate standardized factor .h files following FeedIndicator framework conventions. Triggers: "write factor", "写因子", "帮我写因子", "generate factor", "新因子", "/write-factor".
---

# Write-Factor Skill — 因子编写规范

根据用户描述生成标准化的因子 `.h` 文件。所有因子遵循 FeedIndicator 框架约定。

---

## 1. Factor Type Determination（因子类型判断）

根据用户描述判断需要覆写哪些回调：

| 类型 | 回调 | 说明 |
|------|------|------|
| **Book-only** | `onEndBook()` + `calculateX()` | 仅盘口数据计算 |
| **Trade-based** | + `receive(const Feed::Trade&)` | 需要成交数据 |
| **Cancel-based** | + `receive(const Feed::Cancel&)` | 需要撤单数据 |
| **Order-based** | + `receive(const Feed::Order&)` | 需要订单流数据 |
| **Multi-feed** | `receiveSuper()` + `onEndBookSuper()` | 跨合约因子 |

---

## 2. Framework API Reference

### 2.1 FeedIndicator Lifecycle（生命周期回调）

所有因子都是模板类，继承自 `FeedIndicator`。只覆写需要的回调：

```
initialize(InitArgs)        → 必须先调 FeedIndicator::initialize(args)
static constexpr size()     → 输出因子数量
static names()              → 因子名称列表
onStarted()                 → 重置所有状态变量
receive(Feed::XXX)          → 事件处理（只覆写需要的）
onEndBook()                 → Book周期结束，做复杂计算，存到成员变量
calculateX()                → 【框架自动调用】在 onEndBook() 之后自动调用，只做 setXValue 输出
```

> **关键：** `calculateX()` 由框架在 `onEndBook()` 之后自动调用，不要在 `onEndBook()` 里手动调 `calculateX()`。
> `calculateX()` 内部保持简单——只负责 `setXValue()` 输出，复杂计算逻辑放到 `onEndBook()` 或其他方法中。

### 2.2 FeedWrapper Data Access（通过 feed() 获取）

**价格（默认都用 mantissa）：**

| 想要什么 | API | 返回类型 |
|----------|-----|----------|
| 买i档价格 | `feed().bid(i)` | `int64_t` |
| 卖i档价格 | `feed().ask(i)` | `int64_t` |
| 中间价 | `feed().midPriceMantissa()` | `double` |
| 最小变动单位 | `feed().tickMantissa()` | `int64_t` |
| 最小变动(double) | `feed().tickDouble()` | `double` |
| 半tick(mantissa) | `feed().halfTickMantissa()` | `double` |
| mantissa转价格因子 | `feed().mantissaToPriceFactor()` | `double` |

**盘口量：**

| 想要什么 | API | 返回类型 |
|----------|-----|----------|
| 买i档挂单量 | `feed().bidSize(i)` | `int` |
| 卖i档挂单量 | `feed().askSize(i)` | `int` |
| 买方总档位数 | `feed().bidNumLevels()` | `unsigned` |
| 卖方总档位数 | `feed().askNumLevels()` | `unsigned` |
| 买i档订单数 | `feed().bidNumOrders(i)` | `int` |
| 卖i档订单数 | `feed().askNumOrders(i)` | `int` |

**成交快照（onEndBook 中可用）：**

| 想要什么 | API | 返回类型 |
|----------|-----|----------|
| 最近成交价 | `feed().trade()` | `int64_t` |
| 最近成交量 | `feed().tradeSize()` | `int32_t` |
| 最近成交方向 | `feed().tradeSide()` | `SideT` |
| 累计成交量 | `feed().totalVolume()` | `int64_t` |
| 累计成交额 | `feed().turnover()` | `double` |

> ⚠️ **成交价信号陷阱**：`feed().trade()`（最近成交价）在**离线回测数据里恒为 0**（Book 快照未填该字段）。任何**成交价驱动的因子信号**（Δlast_trade_price 方向/连续性/位移）**必须**在 `receive(const Feed::Trade& data)` 里用 `data.lastTradePrice()`，不要在 `onEndBook()` 用 `feed().trade()`——否则因子值 100% 全零（zero_ratio=1.0 → check_output_missing）。累计量 `totalVolume()`/`turnover()` 在 `receive(Trade)` 里用 `feed()` 取则正常。

**时间：**

| 想要什么 | API | 返回类型 |
|----------|-----|----------|
| 当前时间 | `feed().time()` | `Timestamp`（用 `.nsec()`） |
| Feed时间 | `feed().feedTime()` | `Timestamp` |
| BBO时间 | `feed().bboTime()` | `Timestamp` |
| 成交时间 | `feed().tradeTime()` | `Timestamp` |

**有效性：**

| 想要什么 | API | 返回类型 |
|----------|-----|----------|
| Feed是否有效 | `feed().isValid()` | `bool` |

**输出：**

| 想要什么 | API |
|----------|-----|
| 设置输出值 | `setXValue(i, XType(val))` |
| 增加输出值 | `increaseXValue(i, XType(val))` |
| 乘以输出值 | `multiplyXValue(i, XType(val))` |
| 重置所有输出 | `resetXValues(resetValue)` |

### 2.3 Feed Event Fields（事件数据字段）

**Feed::Trade — 在 `receive(const Feed::Trade& data)` 中获取：**

| 想要什么 | API | 返回类型 | 备注 |
|----------|-----|----------|------|
| 成交价格 | `data.lastTradePrice()` | `int64_t` | mantissa（**成交价信号唯一可靠来源**，见 §2.2 警示） |
| tick成交均价 | `data.averagePrice()` | `double` | |
| 成交量 | `data.quantity()` | `int32_t` | |
| 成交方向 | `data.side()` | `SideT` | BUY=主动买，SELL=主动卖 |
| 成交时间 | `data.time()` | `Timestamp` | |
| 持仓量 | `data.openInterest()` | `int64_t` | |

**Feed::Order — 在 `receive(const Feed::Order& data)` 中获取：**

| 想要什么 | API | 返回类型 | 备注 |
|----------|-----|----------|------|
| 下单价格 | `data.price()` | `int64_t` | mantissa |
| 下单档位 | `data.level()` | `int` | **0-based**；**-1=特殊（成交）** |
| 下单量 | `data.quantity()` | `int32_t` | |
| 下单方向 | `data.side()` | `SideT` | |
| 初始价格 | `data.initialPrice()` | `int64_t` | mantissa |
| 初始下单量 | `data.initialQuantity()` | `int32_t` | |
| 已成交量 | `data.filledQuantity()` | `int32_t` | |
| 是否IOC | `data.ioc()` | `bool` | |
| 是否改单 | `data.amend()` | `bool` | |

> **重要：** `order.level() == -1` 表示发生了成交，此时 `quantity` 含义特殊（约等于新档位挂单量+成交量，新价格档位可能不存在）。需谨慎处理，不可简化。

**Feed::Cancel — 在 `receive(const Feed::Cancel& data)` 中获取：**

| 想要什么 | API | 返回类型 | 备注 |
|----------|-----|----------|------|
| 撤单档位 | `data.level()` | `int` | **0-based** |
| 撤单量 | `data.quantity()` | `int32_t` | |
| 撤单方向 | `data.side()` | `SideT` | |

**Feed::MidPriceChange：**

| 想要什么 | API | 返回类型 | 备注 |
|----------|-----|----------|------|
| 变动方向 | `data.side()` | `SideT` | |
| 变动价格 | `data.price()` | `int64_t` | mantissa |
| 变动类型 | `data.type()` | `MidPriceUpdate::Type` | CANCEL/SWEEP/IOC/ADDED/IMPLIED |
| 涨跌方向 | `data.direction()` | `bool` | true=涨 |
| 变动后买价 | `data.bidPrice()` | `int64_t` | mantissa |
| 变动后卖价 | `data.askPrice()` | `int64_t` | mantissa |

### 2.4 默认不使用的接口

除非用户明确要求，以下接口不要使用：
- `Feed::TradeSummary` — 默认不用
- `feed().bp()`, `feed().op()`, `feed().bp10()` — 预计算BP/OP，不用
- `feed().bppMantissa()`, `feed().bpp10Mantissa()` — 预计算BPP，不用
- `feed().insideLiq()`, `feed().insideLiqInv()` — 预计算流动性，不用

---

## 3. Variable Mapping（变量映射）

### 默认回调放置规则：

- **盘口数据**（bid/ask/size/levels/tick/mid） → `onEndBook()` 中通过 `feed()` 获取
- **成交数据**（price/qty/side/OI） → `receive(const Feed::Trade& data)` 中通过 `data.*` 获取
- **成交累计**（totalVolume/turnover） → `receive(const Feed::Trade& data)` 中通过 `feed()` 获取
- **订单数据** → `receive(const Feed::Order& data)` 中通过 `data.*` 获取
- **撤单数据** → `receive(const Feed::Cancel& data)` 中通过 `data.*` 获取

### 价格约定：
- **所有价格默认用 mantissa 单位**（int64_t）
- 仅在计算需要时才转 double
- 转换用 `feed().tickDouble()` 或 `feed().mantissaToPriceFactor()`

---

## 4. Standard Factor Template（标准因子模板）

**【硬规则】.h 必须在 `#pragma once` 前含 frontmatter**（`// ---` YAML 块），字段：`xname` / `class_name` / `formula`（多行用 `|`）/ `tags`（数组）/ `params`（dict）/ `operators`（数组，算子绑定）/ `created_ts`。格式严格按 `core/tools/parse_frontmatter.py`（每行 `// ` 前缀，`// ---` 边界）。**这是入库时 `addFactorFromHFile` 提取 formula_text/tags 的源头——漏写会导致三件套（formula_text/tags/emb）缺失**。字段来源：xname/class_name/params 从因子 spec；formula 从 spec.formula；tags 从 spec.tags；created_ts 当天。rewrite 改公式后同步更新 `formula` 字段、保留 frontmatter。

**【算子绑定硬规则】`operators: [op21, op23]`——因子用了 operators 表里哪个算子就写哪个**（库内算子见 `operators` 表，如 op21=IndexAnchoredProfileDecomposition 位置矩族）。这是算子回写链路的权威落点：入库时自动落 `factors.operator_chain` + `factor_operator_usage`（confidence=declared），算子复用统计靠它。spec 带 `operator_refs`/`operators` 字段时**原样抄入**；因子实现某算子语义（如索引加权矩=op21、乘性门控调制=op22、条件分箱响应=op23）但 spec 未标时，写因子者负责补上。没绑任何算子可省略本行，但 cognize 协议产出的 contract/repair_contract 候选不允许省略。

```cpp
// ---
// xname: FactorName_w21
// class_name: FactorName
// formula: |
//   _value1 = computeSomething()
//   _value2 = computeOther()
// tags: [order_book, imbalance, exponential_decay]
// params: {window: 21}
// operators: [op21, op23]
// created_ts: 2026-06-26
// ---
#pragma once
#include <cmath>
#include <vector>
#include <array>
#include <algorithm>

// [一句话因子描述]
template <class Param1=DefaultValue, unsigned int MaxLevels=5>
class FactorName : public FeedIndicator {
public:
    static_assert(MaxLevels > 0 && MaxLevels <= 25, "MaxLevels must be 1~25");

    void initialize(const InitArgs& args) {
        FeedIndicator::initialize(args);
        // 预计算（如衰减系数等）
    }

    static constexpr size_t size() {
        return N;  // 输出因子数量
    }

    static const std::vector<std::string> names() {
        return { "factor_name_param_info_1", "factor_name_param_info_2" };
    }

    void onStarted() {
        // 重置所有成员变量
    }

    using FeedIndicator::receive;

    // 按需覆写事件回调：
    // void receive(const Feed::Trade& data) { ... }
    // void receive(const Feed::Order& data) { ... }
    // void receive(const Feed::Cancel& data) { ... }
    // 不需要的回调不要写（基类提供空默认实现）

    void onEndBook() {
        // 主计算逻辑：复杂计算都在这里完成，结果存到成员变量
        _value1 = computeSomething();
        _value2 = computeOther();
    }

    // 框架在 onEndBook() 之后自动调用，不要手动调
    void calculateX() {
        setXValue(0, XType(_value1));
        setXValue(1, XType(_value2));
    }

private:
    using PriceT = int64_t;
    using QuantT = double;

    // 状态变量（_ 前缀）
};
```

### Template Parameter Rules（模板参数规则）

**重要可配置参数必须作为模板参数**，不能硬编码常量。包括：
- 衰减系数（level decay, packet decay）
- 窗口大小
- 档位数
- 幂次
- 任何显著影响因子行为的参数

**double 不能直接做模板参数**（C++17 限制）。必须用框架的 `DoubleCreator<Mantissa, Exponent>` 模式：

```cpp
// 错误 — double 不能做非类型模板参数：
template <double Decay = 0.9, unsigned MaxLevels = 5>

// 正确 — DoubleCreator<Mantissa, Exponent>，value = Mantissa × 10^Exponent：
template <class LevelDecay = DoubleCreator<9, -1>, unsigned int MaxLevels = 5>
// LevelDecay::value = 9 × 10^(-1) = 0.9

// 常用 DoubleCreator 示例：
// DoubleCreator<9, -1>  → 0.9   （常用level衰减）
// DoubleCreator<5, -1>  → 0.5
// DoubleCreator<99, -2> → 0.99
// DoubleCreator<100, 0> → 100   （窗口大小）
// DoubleCreator<50, 0>  → 50
// DoubleCreator<3, 0>   → 3

// 整数参数可以直接使用：
template <unsigned int MaxLevels = 5, int PowerN = 1>
template <size_t NTick = 5, unsigned int OFWindow = 3>
```

**在代码中访问模板参数值：**
- `LevelDecay::value` → double 值（如 0.9）
- `LevelDecay::mantissa` → 尾数（如 9）
- `LevelDecay::exponent` → 指数（如 -1）

**因子命名应包含参数信息：**
```cpp
static const std::vector<std::string> names() {
    std::string p = LevelDecay::decimal().asString() + "_" + std::to_string(MaxLevels);
    return { "factor_name_" + p };
}
```

### Structural Rules（结构规则）
- 每个因子必须有 `using FeedIndicator::receive;`
- 每个因子必须在 `initialize()` 中调用 `FeedIndicator::initialize(args)`
- `onEndBook()` 通常在末尾调用 `calculateX()`
- `calculateX()` 用 `setXValue(i, XType(val))` 输出
- 不需要的事件回调不要写（基类提供空默认实现）

---

## 5. Common Patterns（常用模式）

### Pattern: Bid/Ask Change Detection（买卖价变动检测）

适用于 onEndBook 型因子，当最优价变化时需要重置状态：

```cpp
PriceT _lastBid{};
PriceT _lastAsk{};

void onEndBook() {
    if (_lastBid != feed().bid() || _lastAsk != feed().ask()) {
        _lastBid = feed().bid();
        _lastAsk = feed().ask();
        // 价格变了 → 重置状态
    }
    // ...
}
```

### Pattern: Decay Coefficient Precomputation（衰减系数预计算）

适用于指数衰减因子：

```cpp
std::array<QuantT, MaxLevels> _levelDecay{};

void initialize(const InitArgs& args) {
    FeedIndicator::initialize(args);
    _levelDecay[0] = 1.0;
    for (unsigned i = 1; i < MaxLevels; i++) {
        _levelDecay[i] = _levelDecay[i - 1] * LevelDecay::value;
    }
}
```

### Pattern: Prev/Curr Level Tracking（前后档位追踪）

适用于 OFI 类因子，追踪每档变化：

```cpp
std::array<int64_t, MaxLevels> _prev_bid_prices{};
std::array<int, MaxLevels> _prev_bid_volumes{};

void receive(const Feed::Order& order) {
    const unsigned available_levels = std::min(MaxLevels,
        std::min(feed().bidNumLevels(), feed().askNumLevels()));
    for (unsigned i = 0; i < available_levels; ++i) {
        int64_t curr_bid = feed().bid(i);
        int curr_vol = feed().bidSize(i);
        if (curr_bid > _prev_bid_prices[i]) { /* 新增挂单 */ }
        else if (curr_bid < _prev_bid_prices[i]) { /* 撤单/成交 */ }
        else { /* 量变化：delta */ }
        _prev_bid_prices[i] = curr_bid;
        _prev_bid_volumes[i] = curr_vol;
    }
}
```

### Pattern: Multi-Feed Super（跨合约因子）

适用于需要聚合多合约数据的因子（如指数/价差/OI加权）：

**关键区别：**

| 方面 | 单合约 | 多合约（Super） |
|------|--------|----------------|
| 事件回调 | `receive(const Feed::Trade&)` | `receiveSuper(FeedNumberT feedId, const T& data)` |
| Book结束 | `onEndBook()` | `onEndBookSuper(FeedNumberT feedId)` |
| 数据获取 | `feed().bid(i)` | `_feedWrappers[feedId]->bid(i)` |
| 输出时机 | `onEndBook()` 末尾 | `onEndBookSuper()` 且 `feedId == _feedIndex` 时 |

**初始化 — 必须存储 feedWrappers：**

```cpp
void initialize(const InitArgs& args) {
    FeedIndicator::initialize(args);
    for (auto wrapper : args._feedWrappers) {
        _feedWrappers.emplace_back(wrapper);
    }
    _feedIndex = args._feedIndex;
    const size_t feedCount = _feedWrappers.size();
    _bid_per_feed.resize(feedCount, 0);
    _ask_per_feed.resize(feedCount, 0);
}

// 成员变量：
std::vector<FeedWrapper*> _feedWrappers;
size_t _feedIndex{};
std::vector<PriceT> _bid_per_feed;
std::vector<PriceT> _ask_per_feed;
```

**事件处理 — template receiveSuper + 类型分发：**

```cpp
template<typename T>
void receiveSuper(FeedNumberT feedId, const T& data) {
    if constexpr (std::is_same_v<T, Feed::Trade>) {
        _openinterest_per_feed[feedId] = double(data.openInterest());
    }
    else if constexpr (std::is_same_v<T, Feed::Order>) {
        // 处理特定合约的订单
    }
}
```

**Book结束 — 仅为主合约输出：**

```cpp
void onEndBookSuper(FeedNumberT feedId) {
    auto* fw = _feedWrappers[feedId];
    _bid_per_feed[feedId] = fw->bid();
    _ask_per_feed[feedId] = fw->ask();

    // 聚合计算...
    computeMergedFactor();

    if (feedId == _feedIndex) {
        calculateX();
    }
}
```

---

## 6. Safety Guidelines（安全计算准则）

**核心原则：** 避免除零，计算简洁高效。

**规则：**
1. 除法前必须检查分母：`if (std::abs(den) < 1e-12) return 0.0;`
2. 最终结果用 `std::isfinite()` 检查：`if (!std::isfinite(val)) val = 0.0;`
3. 适当使用 `std::clamp()` 限制输出范围
4. 用 `std::log(std::max(val, 1e-20))` 代替裸 `std::log(val)`
5. 因子内保持 EPSILON 一致（推荐 `1e-12` 或 `1e-20`）
6. **不要过度工程化** — 除法前简单的 `> EPS` 检查通常就足够了

**不要**在因子里包含完整的 safeMath 工具集（sanitizeValue, safeDivide, safeLog, safePow），除非因子确实需要全部。安全级别应与计算复杂度匹配。

---

## 6.5 STL/运行期陷阱（编译/运行期正确性）

§6 管计算安全(判零/isfinite),本节管**编译期 STL 误用**和**运行期崩溃**——历史高频踩坑点,write/rewrite 时对照。

**编译期(STL 误用 → 编译错)**:
1. `std::deque` 不能调 `reserve()`;换 vector 或删 reserve
2. `std::vector` 不能调 `push_front() / pop_front()`
3. `std::accumulate` → `#include <numeric>`
4. `std::cout / cerr` → `#include <iostream>`
5. `std::unordered_map` → `#include <unordered_map>`
6. `std::transform / sort / clamp / min / max` → `#include <algorithm>`
7. `std::function` → `#include <functional>`
8. `std::isfinite` / `std::tanh` / `std::log` → `#include <cmath>`
9. 模板类的 using alias / typedef 必须放 public 区段

**框架 API 类型**:
10. `feed().bid(i)` / `feed().ask(i)` 返回 int64_t,与 double 运算前先 cast
11. `feed().bidSize(i)` / `feed().askSize(i)` 返回 int
12. `Feed::Order.level()` 返回 int,-1 表 trade/cross,0 是 best level
13. 不要在 `calculateX()` 里调 `onEndBook()` 或反过来
14. `onEndBook()` 做复杂计算,`calculateX()` 只做 `setXValue(0, XType(val))`
15. **`InitArgs` 字段访问必须 `_feedIndex`(带下划线前缀)**,不是 `feedIndex`——`args.feedIndex` 编译失败(`has no member named 'feedIndex'; did you mean '_feedIndex'`)。`_feedWrappers` 同理。types.h 声明无下划线但平台编译环境实际带下划线。
16. **成交价信号**(`last_trade_price` 方向/连续性/位移)必须 `receive(const Feed::Trade& data)` 用 `data.lastTradePrice()`;`onEndBook()` 里 `feed().trade()` 在离线数据恒 0 → 因子全零 `check_output_missing`(见 §2.2 警示)。

**运行期崩溃(编译过但跑数据崩 → SIGABRT 134 / SIGSEGV 139 core dump)**:
17. **所有 per-feed 容器(`vector`/`deque`/`array`)必须在 `initialize` 或 `onStarted` 里 resize 到 `_numFeeds`**,否则 `onEndBookSuper(feedId)` 里 `_container[feedId]` 越界 → SIGABRT。**运行期崩溃头号原因**。
18. feed 档位不足时 `bidSize/askSize(i)` 越界 → 用 `availableLevels = min(MaxLevels, min(bidNumLevels, askNumLevels))` 约束循环上界,`L==0` 直接返回。
19. 除法/log 加 eps 保底(`std::max(v, 1e-20)`)+ 最终 `std::isfinite` 守卫,防 NaN/Inf 传播成 UB。
20. 多 feed 因子:跨品种聚合只在主 feed(`feedId == _feedIndex`)触发输出,其余 feed 只更新各自状态;冷启动未就绪(容器空/样本不足)输出 0,不访问空容器。
21. **状态容器(`vector` ring 等)必须在 `initialize()` 里完成首次 assign/resize,不能只在 `onStarted()` 里做**。平台 DAG 回放路径存在 `onEndBook()` 先于 `onStarted()` 到达的时序:只在 `onStarted()` 初始化 → 首批 book 到达时容器还是空的 → 空 `vector` 索引写入 → SIGSEGV(exit 134 core dumped),DAG 全部 93 个 map 实例同型崩溃,check 层只看到 `check_failed(exit=3)` 无任何因子侧错误信号。**正确写法: `initialize()` 和 `onStarted()` 都 assign(前者保首帧前就绪,后者保重置语义),成员声明同时给默认尺寸兜底**(`std::array` 或带 `{}` 初始化)。实证案例 2026-08-25: `DepthPosMomentThickWallCentroid_W200` 三个 ring 只在 `onStarted` assign,连续 3 次 check_failed;补 `initialize()` assign 后同配置一次通过。

---

## 7. Naming Conventions（命名规范）

| 项目 | 规范 | 示例 |
|------|------|------|
| 类名 | PascalCase，描述性 | `CancelPressure`, `BookSlopeImbalance` |
| 因子输出名 | snake_case + 参数后缀 | `sqy0_cancel_buy_sell_diff` |
| 成员变量 | `_` 前缀 | `_bid`, `_askSize`, `_decayFactor` |
| 模板参数 | PascalCase | `LevelDecay`, `MaxLevels`, `PacketDecay` |
| 类型别名 | PascalCase + T | `PriceT = int64_t`, `QuantT = double` |
| 枚举索引 | `e_name` 或 `UPPER_CASE` | `e_x1`, `FRONT_BACK_IMB` |

---

## 8. Generation Rules（生成规则）

生成新因子时，按以下步骤：

### Step 1: 判断因子类型
根据用户描述选择回调组合。

### Step 2: 选择模板参数
- 需要衰减？ → `class LevelDecay=DoubleCreator<9,-1>`
- 档位数？ → `unsigned int MaxLevels=5`
- packet衰减？ → `class PacketDecay=DoubleCreator<9,-1>`
- 窗口大小？ → `class WindowSize=DoubleCreator<50,0>`

### Step 3: 应用安全准则
根据计算复杂度匹配安全级别。

### Step 4: 使用正确的变量映射
每种数据源用正确的 API 和回调位置。

### Step 5: 包含必要模板代码
- `using FeedIndicator::receive;`
- `FeedIndicator::initialize(args)` 在 `initialize()` 中
- **有状态容器(ring buffer 等)在 `initialize()` 中首次 assign/resize**(§6.5 条 21:平台回放 `onEndBook` 可能先于 `onStarted` 到达,只靠 `onStarted` 初始化会空容器崩溃)
- 所有状态在 `onStarted()` 中重置

### Step 6: 自包含输出
每个因子文件完全独立，除框架头文件外无外部依赖。

---

## 8.5 Diagnosis-Driven Modification（诊断驱动修改）

当 run-factor-agent 传入 **diagnosis**（因子质量失败的可执行诊断）时，**不要从头生成**，而是读现有 .h 改局部逻辑。

输入会带：
- 现有 .h 文件路径（必须先 Read 现有代码，理解上下文）
- `diagnosis.nature`：一句话定性（如"因子值近全0，平台跳过 IC"）
- `diagnosis.root_cause_candidates`：按可能性排序的修复方向
- `diagnosis.fix_hint`：最终修复指引

### 修改流程

1. **Read 现有 .h**，定位 `onEndBook()` / `calculateX()` 的主计算逻辑
2. **逐条对照 root_cause_candidates**，判断哪条最匹配现状：
   - 硬门控？→ 看 `volHigh ? x : 0` / 类似的条件输出分支
   - 冷启动？→ 看 `_xxx.size() >= N` 之类的门槛
   - 信号稀疏？→ 看触发条件 / 分位阈值
   - NaN/极值？→ 看 `log()` / 除法有无保底
3. **按 fix_hint 改**（最小改动，不重写整个因子）：
   - 降分位：`VOL_QUANTILE = 0.80` → `0.50`
   - 软化门控：`out = volHigh ? lr : 0.0` → `out = sigmoid(20*(curStd-qThresh)) * lr`
   - 缩短冷启动：`>= 30` → `>= 5`
   - 保底：`std::log(H+EPS)` → `std::log(std::max(H, 1e-20))`
4. **保留 frontmatter**（xname/class_name/formula 等不要动，改完公式描述若语义变了可更新 formula 字段）
5. **保留因子类名**（不重命名，沿用原 xname 重提交，便于平台累积对比）

### 边界：什么算"不可救"

诊断若标注"不可救"（如 `check_failed` 的 traceback 指向平台/框架而非因子代码），write-factor **不要硬改**，返回原文件，让 agent 走 give_up。强行改不可救的因子只会浪费 quality_budget。

---

## Quick Reference Card（速查卡）

生成因子时的自检清单：

- [ ] 继承 `FeedIndicator`
- [ ] `using FeedIndicator::receive;` 已包含
- [ ] `initialize()` 调用了 `FeedIndicator::initialize(args)`
- [ ] 重要参数已放入模板（double 用 DoubleCreator）
- [ ] `onStarted()` 重置了所有成员变量
- [ ] 只覆写了需要的事件回调（不写空的）
- [ ] 价格默认用 mantissa
- [ ] 除法有判零保护
- [ ] 最终结果有 `isfinite` 检查
- [ ] `onEndBook()` 做复杂计算，存到成员变量（不要手动调 `calculateX()`）
- [ ] `calculateX()` 只做 `setXValue(i, XType(val))` 输出（框架自动调用）
- [ ] 因子名包含参数信息

---

## 9. Reference Files（参考文件）

本 skill 目录下包含框架源文件，写复杂因子时可参考：

| 文件 | 内容 |
|------|------|
| `feature01.h` | 因子模板，展示所有可用回调（注释形式） |
| `feed_indicator.h` | FeedIndicator 基类，定义所有生命周期回调 |
| `types.h` | 核心类型定义（XType, FeedWrapper, Feed事件等） |
| `types.cpp` | FeedWrapper 和 Feed 事件的默认实现（全返回0/null） |

遇到不确定的 API 用法时，直接读取这些文件确认。
