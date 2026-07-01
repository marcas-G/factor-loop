#pragma once
#include <cstdint>
#include <cstddef>
#include <string>
#include <limits>
#include <cmath>
#include <array>
#include <ratio>
#include <chrono>
#include <boost/variant.hpp>
#include <vector>
#include <ostream>


typedef float XType;
typedef int64_t OrderIdT;

// Book cache
struct Level {
  int64_t price{};
  int size{};
  int orders{};
};

typedef size_t FeedNumberT;

class FeedWrapper;

struct InitArgs {
  FeedNumberT feedIndex{};
  // 兼容 multi-feed 因子（args._feedWrappers / args._targetFeedWrapper）
  std::vector<FeedWrapper*> _feedWrappers{};
  FeedWrapper* _targetFeedWrapper = nullptr;
};

/**
 * Represents the side of a price/trade/order
 *
 * A trade message side is the side of the aggressor's order,
 * **NOT** the side of the book the trade falls on.
 *
 * Client code is exposed  with only one Side type (SideT), which facilitates
 * comparisons and assignment.
 *
 */
class SideT {
public:
  // Note that side has different meanings when applied to prices/trades/orders
  enum SideType {
    // Prices - on ask side of book.
    // Trades - aggressor sold (on buy side of book)
    // Orders - sell orders
    SELL,
    // Prices - on bid side of book.
    // Trades - aggressor bought (on sell side of book)
    // Orders - buy orders
    BUY,
    // Prices - between inside bid and inside ask in book.
    // Trades - meaningless
    // Orders - meaningless
    NONE,
    // Prices - when bid and ask cross (allowed pre-open)
    // Trades - meaningless
    // Orders - meaningless
    BOTH,
    // When side is not yet set
    UNKNOWN
  };

  constexpr SideT() = default;
  constexpr SideT(const SideType side) : _value(side) {}
  constexpr explicit SideT(bool isBuy) : _value(isBuy ? BUY : SELL) {}
  constexpr SideType value() const { return _value; }

  // returns the opposite side (NONE, BOTH and UNKNOWN remain the same as theirselves)
  constexpr SideT opposite() const {
    return (_value == BUY)
      ? SELL
      : (_value == SELL ? BUY : _value);
  }

  // Returns true if is either BUY or SELL
  constexpr bool isBuyOrSell() const {
    return _value == BUY || _value == SELL;
  }

  constexpr bool isBuy() const {
    return _value == BUY;
  }

  constexpr bool isSell() const {
    return _value == SELL;
  }

  constexpr bool isBoth() const {
    return _value == BOTH;
  }

  constexpr bool isNone() const {
    return _value == NONE;
  }

  constexpr bool isUnknown() const {
    return _value == UNKNOWN;
  }

private:
  SideType _value {UNKNOWN};
};

inline constexpr bool operator==(const SideT& left, const SideT& right) {
  return left.value() == right.value();
}

inline constexpr bool operator!=(const SideT& left, const SideT& right) {
  return left.value() != right.value();
}

class Timestamp {
public:
  constexpr Timestamp() = default;
  explicit constexpr Timestamp(const int64_t time) : _nsec(time) {}

  int64_t nsec() const { return _nsec; }
  bool isZero() const { return _nsec == 0; }

  constexpr bool operator==(const Timestamp& other) const;
  constexpr bool operator!=(const Timestamp& other) const;
  constexpr bool operator<(const Timestamp& other) const;
  constexpr bool operator<=(const Timestamp& other) const;
  constexpr bool operator>(const Timestamp& other) const;
  constexpr bool operator>=(const Timestamp& other) const;

private:
  int64_t _nsec{};
};

inline constexpr bool Timestamp::operator==(const Timestamp& other) const {
  return _nsec == other._nsec;
}

inline constexpr bool Timestamp::operator!=(const Timestamp& other) const {
  return _nsec != other._nsec;
}

inline constexpr bool Timestamp::operator<(const Timestamp& other) const {
  return _nsec < other._nsec;
}

inline constexpr bool Timestamp::operator<=(const Timestamp& other) const {
  return _nsec <= other._nsec;
}

inline constexpr bool Timestamp::operator>(const Timestamp& other) const {
  return _nsec > other._nsec;
}

inline constexpr bool Timestamp::operator>=(const Timestamp& other) const {
  return _nsec >= other._nsec;
}

class Exchange {
public:
  typedef enum {
    UNKNOWN = 0,
    eSHFE,
    eDCE,
    eZCE,
    eCFFEX,
    eGFEX,

    eLast
  } Id_t;

  static constexpr char const* Names[] =
  {
    "UNKNOWN",
    "SHFE",
    "DCE",
    "ZCE",
    "CFFEX",
    "GFEX"
  };

  static const char* name(Id_t id);

  static Id_t fromString(const std::string& str);
};

class TimeDiff {
public:
  constexpr TimeDiff() = default;
  explicit constexpr TimeDiff(const int64_t nanoseconds)
    : _nsec(nanoseconds) {}

  constexpr int64_t nsec() const { return _nsec; }

  static constexpr TimeDiff nanoseconds(int64_t val) {
    return fromUnits<std::nano>(val);
  }

  static constexpr TimeDiff microseconds(int64_t val) {
    return fromUnits<std::micro>(val);
  }

  static constexpr TimeDiff milliseconds(int64_t val) {
    return fromUnits<std::milli>(val);
  }

  static constexpr TimeDiff seconds(int64_t val) {
    return fromUnits<std::ratio<1>>(val);
  }

  static constexpr TimeDiff minutes(int64_t val) {
    return fromUnits<std::chrono::minutes::period>(val);
  }

  static constexpr TimeDiff hours(int64_t val) {
    return fromUnits<std::chrono::hours::period>(val);
  }
private:
  template <typename FromRatio>
  static constexpr TimeDiff fromUnits(int64_t t) {
    using ratio = std::ratio_divide<FromRatio, std::nano>;
    return TimeDiff(t * ratio::num / ratio::den);
  }

private:
  int64_t _nsec{};
};

class Decimal {
public:
  Decimal() = default;
  Decimal(int64_t m, int32_t e) : _m(m), _e(e) {}
  int64_t mantissa() const { return _m; }
  int32_t exponent() const { return _e; }
  bool isZero() const { return _m == 0; }
  bool isNegative() const { return _m < 0; }
  bool isPositive() const { return _m > 0; }
  bool isFinite() const { return _e != std::numeric_limits<int32_t>::min(); }
  double asDouble() const {
    return double(_m) * std::pow(10, double(_e));
  }
  // 兼容因子代码中常见的 PacketDecay::decimal().asString() 调用
  std::string asString() const {
    char buf[64];
    if (_e == 0) {
      std::snprintf(buf, sizeof(buf), "%lld", (long long)_m);
    } else {
      std::snprintf(buf, sizeof(buf), "%llde%d", (long long)_m, _e);
    }
    return std::string(buf);
  }

private:
  int64_t _m; // Mantissa
  int32_t _e; // Exponent
};

class ImpliedMarketFeed {
public:
  bool valid() const;

  explicit operator bool() const { return false; }

  // combined book accessors.
  int64_t bid(unsigned level = 0) const;
  int64_t ask(unsigned level = 0) const;
  int32_t bidSize(unsigned level = 0) const;
  int32_t askSize(unsigned level = 0) const;

  unsigned int bidNumLevels() const;
  unsigned int askNumLevels() const;

  int32_t bidSizeAtPrice(int64_t price) const;
  int32_t askSizeAtPrice(int64_t price) const;

  // implied book accessors
  int64_t impliedBid(unsigned level = 0) const;
  int64_t impliedAsk(unsigned level = 0) const;
  int32_t impliedBidSize(unsigned level = 0) const;
  int32_t impliedAskSize(unsigned level = 0) const;

  unsigned int impliedBidNumLevels() const;
  unsigned int impliedAskNumLevels() const;

  int32_t impliedBidSizeAtPrice(int64_t price) const;
  int32_t impliedAskSizeAtPrice(int64_t price) const;
};

class Instrument {
public:

  const std::string& name() const;

  const std::string& basename() const;

  const Exchange::Id_t exchange() const;

  // gives the ticksize of prices, i.e. the smallest possible diff in price
  const Decimal& tickSize() const;

  unsigned scaleFactor() const;

  // the step size of quantity, i.e. the smallest possible qty
  double stepSize() const;

  double sizeMultiplier() const;

  double notionalPriceFactor() const;

  double tickValue() const;

  // multiply converts price -> mantissa.
  double priceToMantissaFactor() const;

  // multiply converts mantissa -> price
  double mantissaToPriceFactor() const;

  int priceExp() const;

  bool isInverse() const;

  bool useNumOfContracts() const;

  Timestamp expirationTime() const;

  int roundLotSize() const;

  int minFireSize() const;

  const std::string& symbol() const;
};

namespace Feed {

class OrderEvent {
public:
  const Timestamp& time() const;

  SideT side() const;

  OrderIdT id() const;

  int64_t price() const;

  int level() const;

  int32_t quantity() const;

  const Timestamp& transactTime() const;//成交的时间

  const Timestamp& matchEngineTime() const;//
};

class Order : public OrderEvent {
public:
  int64_t initialPrice() const;

  int initialLevel() const;

  int32_t initialQuantity() const;

  int32_t filledQuantity() const;

  int32_t impliedQuantity() const;

  int32_t initialFilledQuantity() const;

  bool ioc() const;

  bool nonDisplayable() const;

  bool nonNative() const;

  bool amend() const;
};

/**
 * A partial or full order cancel
 *
 * The current implementation assumes that partial cancels do not
 * occur (except the case of equities, for which they are explicitly
 * given). So like orders, the Order Count for a Cancel should generally
 * have inclusive boundaries and represents a set of integer values.
 */
class Cancel : public OrderEvent {
};

/**
 * An accumulated Trade at a single price level
 *
 * The time given is the time of the LAST trade message
 *  that provided the information that allow us to reliably say
 *  that such a trade occured.
 */
class Trade : public OrderEvent {
public:
  int32_t impliedQuantity() const;// 针对dce的book，dce有套保，故而有俩个book。

  int64_t openInterest() const;

  double averagePrice() const;

  int64_t lastTradePrice() const;
};

class TradeSummary : public OrderEvent {
public:
 uint64_t seqNum() const;

 int32_t totalQuantity() const;

 int64_t aggressivePrice() const;
};

class IcebergFill : public OrderEvent {
};

class IcebergRefresh : public OrderEvent {
};

namespace MidPriceUpdate {

enum Type {
  UNKNOWN,
  CANCEL,
  SWEEP,
  IOC,
  ADDED,
  BLACK,
  IMPLIED
};

} // end namespace MidPriceUpdate


/**
 * A record of a change in the bid and/or ask
 */
class MidPriceChange {
public:
  const Timestamp& time() const;

  const Instrument& instrument() const;

  // Side that was affected
  const SideT& side() const;

  int64_t price() const;

  Feed::MidPriceUpdate::Type type() const;

  // impact on the MidPrice (true means increases)
  bool direction() const;

  int64_t bidPrice() const;

  int64_t askPrice() const;
};

struct ZcedTrade {
  // overall
  int64_t totalVolume{};
  double turnover{};
  // since the last pulse
  int32_t quantity{};
  int64_t lastTradePrice{};
  double averagePrice{};
  SideT side;
};

struct ChinaOrderStats {
  uint32_t totalBidOrderNum;
  uint32_t totalAskOrderNum;
  double weightedAvgBidOrderPrice;
  double weightedAvgAskOrderPrice;
};

struct PriceQty {
  int64_t price{}; // interval is price : price + 2 ticks.
  // All of these quantities are the total traded amount so far
  // in the day in the price interval denoted above.
  uint32_t buyOpenTradedQty{};
  uint32_t buyCloseTradedQty{};
  uint32_t sellOpenTradedQty{};
  uint32_t sellCloseTradedQty{};
  // deltaQty: buyOpenTradedQty + buyCloseTradedQty from last ChinaMatchPriceQty
  // with the same price.
  uint32_t deltaQty{};
};

struct ChinaMatchPriceQty {
  std::array<PriceQty, 5> priceQty;
  bool allZeroDeltas{}; // true if all the prices have 0 delta traded.
};

struct Noaa {
  Timestamp timestamp;
  using MessageType = boost::variant<
    ZcedTrade,
    ChinaOrderStats,
    ChinaMatchPriceQty>;

  MessageType message;
};

} // end namespace Feed

class FeedWrapper {
public:
  static constexpr unsigned MaxLevels = 25;

  int64_t bid(unsigned level = 0) const;

  int64_t ask(unsigned level = 0) const;

  int bidSize(unsigned level = 0) const;

  int askSize(unsigned level = 0) const;

  unsigned int bidNumLevels() const;

  unsigned int askNumLevels() const;

  int bidNumOrders(unsigned level = 0) const;

  int askNumOrders(unsigned level = 0) const;

  int64_t outsideBid() const;

  int64_t outsideAsk() const;

  bool isOrderBased() const;

  const Instrument& instrument() const;

  int64_t tickMantissa() const;

  double tickDouble() const;

  double invTickMantissa() const;

  double midPriceMantissa() const;
  double midPriceDouble() const;
  double midPriceTick() const;

  bool isValid() const;

  int flow() const;
  const Timestamp& time() const;
  const Timestamp& feedTime() const;
  const Timestamp& fillTime() const;
  const Timestamp& bboTime() const;
  const Timestamp& tradeMpcTime() const;
  const Timestamp& tradeTime() const;
  bool gap() const;
  bool hasImpliedMarketFeed() const;
  ImpliedMarketFeed impliedMarketFeed() const;
  bool isImplied() const;
  double turnover() const;
  int64_t totalVolume() const;
  int bidSizeAtPrice(int64_t price) const;
  int askSizeAtPrice(int64_t price) const;
  int bidOrdersAtPrice(int64_t price) const;
  int askOrdersAtPrice(int64_t price) const;

  int32_t tradeSize() const;
  int64_t trade() const;
  const SideT& tradeSide() const;
  int64_t lastSequenceNumber() const;

  XType insideLiqConstant() const;
  XType insideLiqConstantInv() const;
  XType insideLiq() const;
  XType insideLiqInv() const;

  const Timestamp& managerTime();
  unsigned int volume() const;
  bool previousPriceFlip() const;
  int bidLevelForPrice(int64_t price);

  int askLevelForPrice(int64_t price) const;

  bool lastTradePriceValid() const;
  int64_t lastTradePriceMantissa() const;
  double lastTradePriceDouble() const;

  double lastTradeMidPriceMantissa() const;

  double lastTradeMidPriceDouble() const;

  SideT lastTradeSide() const;

  const Timestamp& lastMidPriceChangeTime();
  const Timestamp& lastPriceFlipTime();

  double halfTickMantissa();
  double halfTickDouble();

  double mantissaToPriceFactor();

  double bp() const;
  double op() const;
  double bp10() const;

  double bppMantissa() const;
  double bppDouble() const;

  double bpp10Mantissa() const;
  double bpp10Double() const;

  template <bool Side>
  const std::array<Level, MaxLevels>& levelVector() const {
    static std::array<Level, MaxLevels> levels;
    return levels;
  }
};

template<int Mantissa, int Exponent>
struct FloatCreator{
public:
    static constexpr int mantissa = Mantissa;
    static constexpr int exponent = Exponent;
    static constexpr double value = Mantissa * std::pow(10.0, Exponent);
};

template<int Mantissa, int Exponent>
struct DoubleCreator{
public:
    static constexpr int mantissa = Mantissa;
    static constexpr int exponent = Exponent;
    static constexpr double value = Mantissa * std::pow(10.0, Exponent);
    static constexpr double inverse = 1 / value;
    static const Decimal decimal() {
      return Decimal((int64_t)Mantissa, (int32_t)Exponent);
    }
};

template<int Mantissa, int Exponent>
constexpr int FloatCreator<Mantissa, Exponent>::mantissa;

template<int Mantissa, int Exponent>
constexpr int FloatCreator<Mantissa, Exponent>::exponent;

template<int Mantissa, int Exponent>
constexpr double FloatCreator<Mantissa, Exponent>::value;

template <int64_t N>
struct TimeDiffValue {
  static constexpr TimeDiff value() { return TimeDiff{N}; }
};

enum TimeSuffix {
  eTimeSuffix_ns = 0,
  eTimeSuffix_us = 1,
  eTimeSuffix_ms = 2,
  eTimeSuffix_s = 3,
  eTimeSuffix_h = 4,
};

template <int N, TimeSuffix Suffix>
struct TimeDiffCreator;

template <int N>
struct TimeDiffCreator<N, eTimeSuffix_ns> : TimeDiffValue<TimeDiff::nanoseconds(N).nsec()> {};

template <int N>
struct TimeDiffCreator<N, eTimeSuffix_us> : TimeDiffValue<TimeDiff::microseconds(N).nsec()> {};

template <int N>
struct TimeDiffCreator<N, eTimeSuffix_ms> : TimeDiffValue<TimeDiff::milliseconds(N).nsec()> {};

template <int N>
struct TimeDiffCreator<N, eTimeSuffix_s> : TimeDiffValue<TimeDiff::seconds(N).nsec()> {};

template <int N>
struct TimeDiffCreator<N, eTimeSuffix_h> : TimeDiffValue<TimeDiff::hours(N).nsec()> {};

