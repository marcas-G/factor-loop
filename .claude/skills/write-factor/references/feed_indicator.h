#pragma once
#include "types.h"


class FeedIndicator {
public:

  static constexpr size_t size();
  static const std::vector<std::string>& names();

  void initialize(const InitArgs& initArgs);

  FeedNumberT feedId() const;

  void receive(const Feed::Trade& data) {}
  void receive(const Feed::TradeSummary& data) {}
  void receive(const Feed::Order& data) {}
  void receive(const Feed::Cancel& data) {}
  void receive(const Feed::IcebergFill& data) {}
  void receive(const Feed::IcebergRefresh& data) {}
  void receive(const Feed::MidPriceChange& data) {}//每个level都更新一下
  void receive(const Feed::Noaa& data) {}

  void beforeBucket() {}

  void afterBucket() {}

  void onStarted() {}

  void onTradeSuper(FeedNumberT feedId) {}

  void onMidPriceChangeSuper(FeedNumberT feedId) {}

  void onPriceFlipSuper(FeedNumberT feedId) {}

  void onEndBookSuper(FeedNumberT feedId) {}

  void onTrade() {}

  void onMidPriceChange() {}

  void onPriceFlip() {}

  void onEndBook() {}

  // The callback will be called only when there is any update (e.g. trade, book update) to this feed,
  // and right before end buffer and before BeforeBucket.
  void calculateX() {}

  bool calculateXAfter() { return false; }

  // The callback will be called only when there is any update (e.g. trade, book update) to this feed,
  // and right before end buffer and before BeforeBucket.
  void calculateXSuper(FeedNumberT feedId) {}

  void onFeedValid() {}
  void onFeedValidSuper(FeedNumberT feedId) {}
  void onFeedInvalid() {}
  void onFeedInvalidSuper(FeedNumberT feedId) {}

  void onTargetPriceFlip(const FeedWrapper& f) {}
  void onTargetMidPriceChange(const FeedWrapper& f) {}

  template<typename T>
  void receiveSuper(FeedNumberT feedId, const T& data) {}
protected:
  const FeedWrapper& feed() const;

  FeedWrapper& feed();

  // return the pointer to X array whose size is xSize()
  // to iterate the values, you can do:
  // XType* v = xValues();
  // for (size_t i = 0; i < xSize(); i++) {
  //   std::cout << v[i];
  // }
  // X values, must be in the same order as names
  const XType* xValues() const;

  XType* xValues();

  size_t xSize() const;

  XType xValue(size_t i);

protected:
  void setXValue(size_t i, XType v);

  void increaseXValue(size_t i, XType increasedBy);

  void multiplyXValue(size_t i, XType multiplyBy);

  void resetXValues(int resetValue);

  void resetXValues(size_t start, size_t length, int resetValue);
};

class ImpulseFeedIndicator : public FeedIndicator {
};

