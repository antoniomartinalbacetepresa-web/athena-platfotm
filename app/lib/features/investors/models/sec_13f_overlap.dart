import 'relevant_investor_activity.dart';

/// An exact as-reported CUSIP co-occurrence, not canonical instrument identity.
class Sec13fSharedCusip {
  const Sec13fSharedCusip({required this.cusip, required this.ciks});

  final String cusip;
  final List<String> ciks;
}

/// Read-only comparison of verified, unamended filings for the same report date.
/// Never infers current holdings, common economic exposure, or portfolio weights.
class Sec13fOverlapReport {
  const Sec13fOverlapReport({
    required this.positionDate,
    required this.managerCount,
    required this.sharedCusips,
  });

  final DateTime positionDate;
  final int managerCount;
  final List<Sec13fSharedCusip> sharedCusips;

  static final RegExp _unambiguousCusip = RegExp(r'^[A-Z0-9]{9}$');

  /// Returns null rather than mixing dates, amendments, or untrusted cohorts.
  static Sec13fOverlapReport? fromFilings(
    List<RelevantInvestorActivity> filings,
  ) {
    if (filings.length < 2 || filings.length > 5) return null;
    final positionDate = filings.first.positionDate;
    final uniqueCiks = filings.map((filing) => filing.cik).toSet();
    if (uniqueCiks.length != filings.length ||
        filings.any(
          (filing) =>
              filing.form != '13F-HR' ||
              filing.sourceProvider != 'SEC EDGAR' ||
              filing.valueUnit != 'thousands_usd_as_reported_by_sec_13f' ||
              !filing.positionDate.isAtSameMomentAs(positionDate),
        )) {
      return null;
    }

    final managersByCusip = <String, Set<String>>{};
    for (final filing in filings) {
      for (final holding in filing.holdings) {
        // PRN, puts, calls and placeholder CUSIPs cannot support this
        // deliberately narrow as-reported share-row comparison.
        if (holding.shareOrPrincipalType != 'SH' ||
            holding.putCall != null ||
            !_unambiguousCusip.hasMatch(holding.cusip)) {
          continue;
        }
        managersByCusip.putIfAbsent(holding.cusip, () => <String>{})
            .add(filing.cik);
      }
    }

    final shared = <Sec13fSharedCusip>[];
    for (final entry in managersByCusip.entries) {
      if (entry.value.length < 2) continue;
      final ciks = entry.value.toList()..sort();
      shared.add(Sec13fSharedCusip(
        cusip: entry.key,
        ciks: List<String>.unmodifiable(ciks),
      ));
    }
    shared.sort((a, b) {
      final byManagers = b.ciks.length.compareTo(a.ciks.length);
      return byManagers != 0 ? byManagers : a.cusip.compareTo(b.cusip);
    });

    return Sec13fOverlapReport(
      positionDate: positionDate,
      managerCount: filings.length,
      sharedCusips: List<Sec13fSharedCusip>.unmodifiable(shared),
    );
  }
}
