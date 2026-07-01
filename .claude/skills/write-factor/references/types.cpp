#include "types.h"

namespace {

const std::string& defaultString() {
  static std::string n;
  return n;
}

const Timestamp& defaultTimestamp() {
  static Timestamp t;
  return t;
}

const Decimal& defaultDecimal() {
  static Decimal ZERO;
  return ZERO;
}

const SideT& defaultSide() {
  static SideT side{SideT::UNKNOWN};
  return side;
}

} // end namespace

const char* Exchange::name(Exchange::Id_t id) {
  return Exchange::Names[int(id)];
}

Exchange::Id_t Exchange::fromString(const std::string& str) {
  for (int i = 0; i < int(Exchange::eLast); ++i) {
    if (str == std::string(Names[i])) {
      return Id_t(i);
    }
  }
  return Exchange::UNKNOWN;
}

int64_t ImpliedMarketFeed::bid(unsigned level) const { return 0; }
int64_t ImpliedMarketFeed::ask(unsigned level) const { return 0; }
int32_t ImpliedMarketFeed::bidSize(unsigned level) const { return 0; }
int32_t ImpliedMarketFeed::askSize(unsigned level) const { return 0; }

unsigned int ImpliedMarketFeed::bidNumLevels() const { return 0; }
unsigned int ImpliedMarketFeed::askNumLevels() const { return 0; }

int32_t ImpliedMarketFeed::bidSizeAtPrice(int64_t price) const { return 0; }
int32_t ImpliedMarketFeed::askSizeAtPrice(int64_t price) const { return 0; }

int64_t ImpliedMarketFeed::impliedBid(unsigned level) const { return 0; }
int64_t ImpliedMarketFeed::impliedAsk(unsigned level) const { return 0; }
int32_t ImpliedMarketFeed::impliedBidSize(unsigned level) const { return 0; }
int32_t ImpliedMarketFeed::impliedAskSize(unsigned level) const { return 0; }

unsigned int ImpliedMarketFeed::impliedBidNumLevels() const { return 0; }
unsigned int ImpliedMarketFeed::impliedAskNumLevels() const { return 0; }

int32_t ImpliedMarketFeed::impliedBidSizeAtPrice(int64_t price) const { return 0; }
int32_t ImpliedMarketFeed::impliedAskSizeAtPrice(int64_t price) const { return 0; }


const std::string& Instrument::name() const {
  return defaultString();
}

const std::string& Instrument::basename() const {
  return defaultString();
}

const Exchange::Id_t Instrument::exchange() const { return Exchange::UNKNOWN; }

const Decimal& Instrument::tickSize() const {
  return defaultDecimal();
}

unsigned Instrument::scaleFactor() const { return 0; }

double Instrument::stepSize() const { return 0; }

double Instrument::sizeMultiplier() const { return 0; }

double Instrument::notionalPriceFactor() const { return 0; }

double Instrument::tickValue() const { return 0; }

double Instrument::priceToMantissaFactor() const { return 0; }

double Instrument::mantissaToPriceFactor() const { return 0; }

int Instrument::priceExp() const { return 0; }

bool Instrument::isInverse() const { return false; }

bool Instrument::useNumOfContracts() const { return false; }

Timestamp Instrument::expirationTime() const {
  return Timestamp{};
}

int Instrument::roundLotSize() const { return 0; }

int Instrument::minFireSize() const { return 0; }

const std::string& Instrument::symbol() const {
  return defaultString();
}

namespace Feed {

const Timestamp& OrderEvent::time() const { return defaultTimestamp(); }

SideT OrderEvent::side() const { return SideT::UNKNOWN; }

OrderIdT OrderEvent::id() const { return 0; }

int64_t OrderEvent::price() const { return 0; }

int OrderEvent::level() const { return 0; }

int32_t OrderEvent::quantity() const { return 0; }

const Timestamp& OrderEvent::transactTime() const { return defaultTimestamp(); }

const Timestamp& OrderEvent::matchEngineTime() const { return defaultTimestamp(); }

int64_t Order::initialPrice() const { return 0; }

int Order::initialLevel() const { return 0; }

int32_t Order::initialQuantity() const { return 0; }

int32_t Order::filledQuantity() const { return 0; }

int32_t Order::impliedQuantity() const { return 0; }

int32_t Order::initialFilledQuantity() const { return 0; }

bool Order::ioc() const { return false; }

bool Order::nonDisplayable() const { return false; }

bool Order::nonNative() const { return false; }

bool Order::amend() const { return false; }

int32_t Trade::impliedQuantity() const { return 0; }

int64_t Trade::openInterest() const { return 0; }

double Trade::averagePrice() const { return 0; }

int64_t Trade::lastTradePrice() const { return 0; }

const Timestamp& MidPriceChange::time() const { return defaultTimestamp(); }

const Instrument& MidPriceChange::instrument() const {
  static const Instrument inst;
  return inst;
}

// Side that was affected
const SideT& MidPriceChange::side() const { return defaultSide(); }

int64_t MidPriceChange::price() const { return 0; }

Feed::MidPriceUpdate::Type MidPriceChange::type() const { return MidPriceUpdate::UNKNOWN; }

// impact on the MidPrice (true means increases)
bool MidPriceChange::direction() const { return false; }

int64_t MidPriceChange::bidPrice() const { return 0; }

int64_t MidPriceChange::askPrice() const { return 0; }

} // end namespace Feed

int64_t FeedWrapper::bid(unsigned level) const { return 0; }

int64_t FeedWrapper::ask(unsigned level) const { return 0; }

int FeedWrapper::bidSize(unsigned level) const { return 0; }

int FeedWrapper::askSize(unsigned level) const { return 0; }

unsigned int FeedWrapper::bidNumLevels() const { return 0; }

unsigned int FeedWrapper::askNumLevels() const { return 0; }

int FeedWrapper::bidNumOrders(unsigned level) const { return 0; }

int FeedWrapper::askNumOrders(unsigned level) const { return 0; }

int64_t FeedWrapper::outsideBid() const { return 0; }

int64_t FeedWrapper::outsideAsk() const { return 0; }

bool FeedWrapper::isOrderBased() const { return false; }

const Instrument& FeedWrapper::instrument() const {
  static Instrument inst;
  return inst;
}

int64_t FeedWrapper::tickMantissa() const { return 0; }

double FeedWrapper::tickDouble() const { return 0; }

double FeedWrapper::invTickMantissa() const { return 0; }

double FeedWrapper::midPriceMantissa() const { return 0; }
double FeedWrapper::midPriceDouble() const { return 0; }
double FeedWrapper::midPriceTick() const { return 0; }

bool FeedWrapper::isValid() const { return false; }

int FeedWrapper::flow() const { return 0; }
const Timestamp& FeedWrapper::time() const { return defaultTimestamp(); }
const Timestamp& FeedWrapper::feedTime() const { return defaultTimestamp(); }
const Timestamp& FeedWrapper::fillTime() const { return defaultTimestamp(); }
const Timestamp& FeedWrapper::bboTime() const { return defaultTimestamp(); }
const Timestamp& FeedWrapper::tradeMpcTime() const { return defaultTimestamp(); }
const Timestamp& FeedWrapper::tradeTime() const { return defaultTimestamp(); }
bool FeedWrapper::gap() const { return false; }
bool FeedWrapper::hasImpliedMarketFeed() const { return false; }
ImpliedMarketFeed FeedWrapper::impliedMarketFeed() const { return ImpliedMarketFeed{}; }
bool FeedWrapper::isImplied() const { return false; }
double FeedWrapper::turnover() const { return 0; }
int64_t FeedWrapper::totalVolume() const { return 0; }
int FeedWrapper::bidSizeAtPrice(int64_t price) const { return 0; }
int FeedWrapper::askSizeAtPrice(int64_t price) const { return 0; }
int FeedWrapper::bidOrdersAtPrice(int64_t price) const { return 0; }
int FeedWrapper::askOrdersAtPrice(int64_t price) const { return 0; }

int32_t FeedWrapper::tradeSize() const { return 0; }
int64_t FeedWrapper::trade() const { return 0; }
const SideT& FeedWrapper::tradeSide() const { return defaultSide(); }
int64_t FeedWrapper::lastSequenceNumber() const { return 0; }

XType FeedWrapper::insideLiqConstant() const { return 0; }
XType FeedWrapper::insideLiqConstantInv() const { return 0; }
XType FeedWrapper::insideLiq() const { return 0; }
XType FeedWrapper::insideLiqInv() const { return 0; }

const Timestamp& FeedWrapper::managerTime() { return defaultTimestamp(); }
unsigned int FeedWrapper::volume() const { return 0; }
bool FeedWrapper::previousPriceFlip() const { return false; }
int FeedWrapper::bidLevelForPrice(int64_t price) { return 0; }

int FeedWrapper::askLevelForPrice(int64_t price) const { return 0; }

bool FeedWrapper::lastTradePriceValid() const { return false; }
int64_t FeedWrapper::lastTradePriceMantissa() const { return 0; }
double FeedWrapper::lastTradePriceDouble() const { return 0; }

double FeedWrapper::lastTradeMidPriceMantissa() const { return 0; }

double FeedWrapper::lastTradeMidPriceDouble() const { return 0; }

SideT FeedWrapper::lastTradeSide() const { return SideT::UNKNOWN; }

const Timestamp& lastMidPriceChangeTime() { return defaultTimestamp(); }
const Timestamp& lastPriceFlipTime() { return defaultTimestamp(); }

double FeedWrapper::halfTickMantissa() { return 0; }
double FeedWrapper::halfTickDouble() { return 0; }

double FeedWrapper::mantissaToPriceFactor() { return 0; }

double FeedWrapper::bp() const { return 0; }
double FeedWrapper::op() const { return 0; }
double FeedWrapper::bp10() const { return 0; }

double FeedWrapper::bppMantissa() const { return 0; }
double FeedWrapper::bppDouble() const { return 0; }

double FeedWrapper::bpp10Mantissa() const { return 0; }
double FeedWrapper::bpp10Double() const { return 0; }

