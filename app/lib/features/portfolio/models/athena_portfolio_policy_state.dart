enum AthenaPortfolioPolicyState {
  reducedLong('reduced_long'),
  fullLong('full_long');

  const AthenaPortfolioPolicyState(this.key);

  final String key;

  static AthenaPortfolioPolicyState? tryParse(Object? value) {
    final normalized = value?.toString().trim().toLowerCase();
    if (normalized == null || normalized.isEmpty) {
      return null;
    }
    for (final state in values) {
      if (state.key == normalized) {
        return state;
      }
    }
    return null;
  }
}
