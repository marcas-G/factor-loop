class SampleFeature001 : public FeedIndicator {
  enum Xs {
    e_x1,
    e_x2,
    XsNum
  };
public:
  // The tatal number of Xs that this feature class produces
  // This function must exist.
  static constexpr size_t size() { return XsNum; }

  // The X names for each X produced by this class
  // This function must exist and the number of Xnames must be equal to the size().
  static const std::vector<std::string>& names() {
    static const std::vector<std::string> names = {"x1", "x2"};
    return names;
  }

  // Market Event Callbacks.
  // The callback functions are only needed when you want to calculate something inside the callback as the corresponding event happens.

  // void receive(const Feed::Trade& data) {}

  // void receive(const Feed::Order& data) {}
  // void receive(const Feed::Cancel& data) {}
  // void receive(const Feed::IcebergFill& data) {}
  // void receive(const Feed::IcebergRefresh& data) {}
  // void receive(const Feed::MidPriceChange& data) {}
  // void receive(const Feed::Noaa& data) {}

  // void beforeBucket() {}

  // void afterBucket() {}

  // void onStarted() {}

  // void onTradeSuper(FeedNumberT feedId) {}

  // void onMidPriceChangeSuper(FeedNumberT feedId) {}

  // void onPriceFlipSuper(FeedNumberT feedId) {}

  // void onEndBookSuper(FeedNumberT feedId) {}

  // void onTrade() {}

  // void onMidPriceChange() {}

  // void onPriceFlip() {}

  // void onEndBook() {}

  // The callback will be called only when there is any update (e.g. trade, book update) to this feed,
  // and right before end buffer and before BeforeBucket.
  // void calculateX() {}

  // bool calculateXAfter() { return false; }

  // The callback will be called only when there is any update (e.g. trade, book update) to this feed,
  // and right before end buffer and before BeforeBucket.
  // void calculateXSuper(FeedNumberT feedId) {}

  // void onFeedValid() {}
  // void onFeedValidSuper(FeedNumberT feedId) {}
  // void onFeedInvalid() {}
  // void onFeedInvalidSuper(FeedNumberT feedId) {}

  // void onTargetPriceFlip(const FeedWrapper& f) {}
  // void onTargetMidPriceChange(const FeedWrapper& f) {}

  // template<typename T>
  // void receiveSuper(FeedNumberT feedId, const T& data) {}
};
