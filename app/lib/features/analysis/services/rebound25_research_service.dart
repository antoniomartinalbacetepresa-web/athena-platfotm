import 'dart:async';
import 'dart:convert';
import 'dart:typed_data';

import 'package:http/http.dart' as http;

import '../../auth/services/auth_session.dart';

const _responseError = FormatException(
  'Respuesta de simulación sintética incompatible.',
);
final _hashPattern = RegExp(r'^[a-f0-9]{64}$');
final _instantPattern = RegExp(
  r'^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}'
  r'(\.[0-9]{1,6})?(Z|[+-]([01][0-9]|2[0-3]):[0-5][0-9])$',
);

Map<String, dynamic> _object(Object? value) {
  if (value is! Map<String, dynamic>) throw _responseError;
  return value;
}

double _number(
  Object? value, {
  bool nonnegative = false,
  bool positive = false,
}) {
  if (value is! num ||
      !value.isFinite ||
      (positive && value <= 0) ||
      (nonnegative && value < 0)) {
    throw _responseError;
  }
  return value.toDouble();
}

int _count(Object? value, {int maximum = 5000}) {
  if (value is! int || value < 0 || value > maximum) throw _responseError;
  return value;
}

String _text(Object? value) {
  if (value is! String ||
      value.isEmpty ||
      value.length > 2000 ||
      value != value.trim() ||
      RegExp(r'[\x00-\x1f\x7f]').hasMatch(value)) {
    throw _responseError;
  }
  return value;
}

DateTime _instant(Object? value) {
  if (value is! String ||
      _instantPattern.matchAsPrefix(value)?.end != value.length) {
    throw _responseError;
  }
  final parsed = DateTime.tryParse(value);
  // DateTime may normalize invalid calendar dates. Check the wall-clock part
  // independently so February 30 cannot masquerade as a valid research clock.
  final wall = DateTime.tryParse('${value.substring(0, 19)}Z');
  if (parsed == null ||
      wall == null ||
      wall.year < 1 ||
      wall.year > 9999 ||
      wall.toIso8601String().substring(0, 19) != value.substring(0, 19)) {
    throw _responseError;
  }
  return parsed.toUtc();
}

String _date(Object? value) {
  if (value is! String ||
      !RegExp(r'^[0-9]{4}-[0-9]{2}-[0-9]{2}$').hasMatch(value)) {
    throw _responseError;
  }
  final parsed = DateTime.tryParse('${value}T00:00:00Z');
  if (parsed == null ||
      parsed.year < 1 ||
      parsed.year > 9999 ||
      parsed.toIso8601String().substring(0, 10) != value) {
    throw _responseError;
  }
  return value;
}

void _sameNumber(Object? actual, num expected) {
  final number = _number(actual);
  final tolerance = 1e-8 * (expected.abs() > 1 ? expected.abs() : 1);
  if (!expected.isFinite || (number - expected).abs() > tolerance) {
    throw _responseError;
  }
}

void _keys(
  Map<String, dynamic> data,
  Set<String> required, [
  Set<String> optional = const {},
]) {
  if (!data.keys.toSet().containsAll(required) ||
      data.keys.any(
        (key) => !required.contains(key) && !optional.contains(key),
      )) {
    throw _responseError;
  }
}

void _finiteJson(Object? value) {
  if (value is num && !value.isFinite) throw _responseError;
  if (value is Map) {
    if (value.keys.any((key) => key is! String)) throw _responseError;
    for (final child in value.values) {
      _finiteJson(child);
    }
  } else if (value is List) {
    for (final child in value) {
      _finiteJson(child);
    }
  } else if (value != null &&
      value is! num &&
      value is! String &&
      value is! bool) {
    throw _responseError;
  }
}

/// Caller-authored synthetic JSON, snapshotted once. No prices or calendars are inferred.
class Rebound25ResearchRequest {
  Rebound25ResearchRequest(Map<String, dynamic> request) {
    try {
      _finiteJson(request);
      encodedBody = jsonEncode(request);
      if (utf8.encode(encodedBody).length >
          Rebound25ResearchService.maxBodyBytes) {
        throw _responseError;
      }
      final data = _object(jsonDecode(encodedBody));
      _keys(data, {
        'evidenceKind',
        'instrumentId',
        'currency',
        'asOf',
        'precommittedAt',
        'expectedSessions',
        'bars',
        'parameters',
      });
      if (data['evidenceKind'] != 'synthetic_fixture' ||
          _text(data['instrumentId']).length > 160 ||
          !RegExp(r'^[A-Z]{3}$').hasMatch(_text(data['currency']))) {
        throw _responseError;
      }
      instrumentId = data['instrumentId'] as String;
      currency = data['currency'] as String;
      asOf = _instant(data['asOf']);
      precommittedAt = _instant(data['precommittedAt']);
      final rawBars = data['bars'];
      final rawSessions = data['expectedSessions'];
      if (rawBars is! List ||
          rawBars.length < 2 ||
          rawBars.length > 5000 ||
          rawSessions is! List ||
          rawSessions.length != rawBars.length) {
        throw _responseError;
      }
      final parameterMap = _object(data['parameters']);
      _keys(
        parameterMap,
        {
          'takeProfitPct',
          'stopLossPct',
          'maxHoldingSessions',
          'commissionBps',
          'spreadBps',
          'slippageBps',
          'orderUnits',
          'minAverageVolume',
          'maxVolumeParticipation',
          'minRelativeVolume',
        },
        {
          'lookbackSessions',
          'minReboundPct',
          'maxConfirmationSessions',
          'version',
        },
      );
      final normalized = <String, dynamic>{};
      for (final entry in const {
        'takeProfitPct': 'take_profit_pct',
        'stopLossPct': 'stop_loss_pct',
        'commissionBps': 'commission_bps',
        'spreadBps': 'spread_bps',
        'slippageBps': 'slippage_bps',
        'orderUnits': 'order_units',
        'minAverageVolume': 'min_average_volume',
        'maxVolumeParticipation': 'max_volume_participation',
        'minRelativeVolume': 'min_relative_volume',
        'minReboundPct': 'min_rebound_pct',
      }.entries) {
        normalized[entry.value] = _number(
          parameterMap.containsKey(entry.key)
              ? parameterMap[entry.key]
              : (entry.key == 'minReboundPct' ? 1 : null),
          positive: const {
            'takeProfitPct',
            'stopLossPct',
            'orderUnits',
            'minAverageVolume',
            'maxVolumeParticipation',
          }.contains(entry.key),
          nonnegative: true,
        );
      }
      for (final entry in const {
        'maxHoldingSessions': 'max_holding_sessions',
        'lookbackSessions': 'lookback_sessions',
        'maxConfirmationSessions': 'max_confirmation_sessions',
      }.entries) {
        final value = parameterMap.containsKey(entry.key)
            ? parameterMap[entry.key]
            : (entry.key == 'lookbackSessions'
                  ? 25
                  : entry.key == 'maxConfirmationSessions'
                  ? 3
                  : null);
        if (_count(value, maximum: 252) < 1) throw _responseError;
        normalized[entry.value] = value;
      }
      normalized['version'] = parameterMap.containsKey('version')
          ? parameterMap['version']
          : 'rebound25-synthetic-v1';
      if (normalized['version'] != 'rebound25-synthetic-v1' ||
          (normalized['stop_loss_pct'] as num) >= 100 ||
          (normalized['max_volume_participation'] as num) > 1 ||
          (normalized['spread_bps'] as num) / 2 +
                  (normalized['slippage_bps'] as num) >=
              10000) {
        throw _responseError;
      }
      parameters = Map.unmodifiable(normalized);
      final parsedBars = <Map<String, dynamic>>[];
      DateTime? previousClose;
      String? previousSession;
      for (var index = 0; index < rawBars.length; index++) {
        final bar = _object(rawBars[index]);
        _keys(bar, {
          'session',
          'openAt',
          'observedAt',
          'availableAt',
          'open',
          'high',
          'low',
          'close',
          'volume',
        });
        final session = _date(bar['session']);
        final opened = _instant(bar['openAt']);
        final observed = _instant(bar['observedAt']);
        final available = _instant(bar['availableAt']);
        final open = _number(bar['open'], positive: true);
        final high = _number(bar['high'], positive: true);
        final low = _number(bar['low'], positive: true);
        final close = _number(bar['close'], positive: true);
        _number(bar['volume'], nonnegative: true);
        if (session != _date(rawSessions[index]) ||
            (previousSession != null &&
                session.compareTo(previousSession) <= 0) ||
            !opened.isBefore(observed) ||
            observed.isAfter(available) ||
            available.isAfter(asOf) ||
            (previousClose != null && !opened.isAfter(previousClose)) ||
            low > open ||
            low > close ||
            high < open ||
            high < close) {
          throw _responseError;
        }
        parsedBars.add(Map.unmodifiable(bar));
        previousClose = observed;
        previousSession = session;
      }
      bars = List.unmodifiable(parsedBars);
      final lookback = parameters['lookback_sessions'] as int;
      if (lookback >= bars.length ||
          precommittedAt.isAfter(_instant(bars[lookback]['openAt']))) {
        throw _responseError;
      }
    } catch (_) {
      throw const FormatException(
        'Solicitud sintética inválida; no se enviaron datos.',
      );
    }
  }

  late final String encodedBody;
  late final String instrumentId;
  late final String currency;
  late final DateTime asOf;
  late final DateTime precommittedAt;
  late final Map<String, dynamic> parameters;
  late final List<Map<String, dynamic>> bars;
}

class Rebound25Signal {
  const Rebound25Signal({
    required this.session,
    required this.outcome,
    required this.decisionAt,
    this.confirmationSession,
  });
  final String session;
  final String outcome;
  final DateTime decisionAt;
  final String? confirmationSession;
}

/// Validated synthetic report. Hash shape is checked, not independently re-attested.
class Rebound25ResearchResult {
  Rebound25ResearchResult._({
    required this.tradeCount,
    required this.totalNetPnl,
    required this.benchmarkHypotheticalPnl,
    required this.parametersFingerprint,
    required this.resultFingerprint,
    required this.instrumentId,
    required this.currency,
    required this.signals,
    required this.warnings,
  });

  factory Rebound25ResearchResult.fromJson(
    Map<String, dynamic> data, {
    required Map<String, dynamic> request,
  }) => Rebound25ResearchResult._parse(data, Rebound25ResearchRequest(request));

  final int tradeCount;
  final double totalNetPnl;
  final double benchmarkHypotheticalPnl;
  final String parametersFingerprint;
  final String resultFingerprint;
  final String instrumentId;
  final String currency;
  final List<Rebound25Signal> signals;
  int get signalCount => signals.length;
  final List<String> warnings;

  static Rebound25ResearchResult _parse(
    Map<String, dynamic> data,
    Rebound25ResearchRequest request,
  ) {
    try {
      _finiteJson(data);
      if (data['schema'] != 'athena.synthetic-rebound-backtest.v1' ||
          data['outputRevision'] != '1.1-buy-and-hold-reporting' ||
          data['evidenceKind'] != 'synthetic_fixture' ||
          data['advisoryStatus'] != 'no_advice' ||
          data['instrumentId'] != request.instrumentId ||
          data['currency'] != request.currency ||
          _instant(data['asOf']) != request.asOf ||
          _instant(data['precommittedAt']) != request.precommittedAt ||
          data['precommitBasis'] !=
              'caller_declared_not_immutable_attestation' ||
          data['calendarBasis'] !=
              'caller_supplied_sessions_not_exchange_attested') {
        throw _responseError;
      }
      for (final field in [
        'productionEligible',
        'historicalPointInTimeEligible',
        'outOfSampleValidated',
        'automaticTrading',
        'ordersEnabled',
      ]) {
        if (data[field] != false) throw _responseError;
      }
      for (final field in [
        'parameterFingerprint',
        'inputFingerprint',
        'resultFingerprint',
      ]) {
        if (data[field] is! String ||
            (data[field] as String).length != 64 ||
            !_hashPattern.hasMatch(data[field] as String)) {
          throw _responseError;
        }
      }
      final protocol = _object(data['parameters']);
      if (protocol.length != request.parameters.length) throw _responseError;
      for (final entry in request.parameters.entries) {
        if (entry.value is int) {
          if (protocol[entry.key] is! int ||
              protocol[entry.key] != entry.value) {
            throw _responseError;
          }
        } else if (entry.value is num) {
          _sameNumber(protocol[entry.key], entry.value as num);
        } else if (protocol[entry.key] != entry.value) {
          throw _responseError;
        }
      }
      final units = protocol['order_units'] as num;
      final adverse =
          ((protocol['spread_bps'] as num) / 2 +
              (protocol['slippage_bps'] as num)) /
          10000;
      final fee = (protocol['commission_bps'] as num) / 10000;
      final lookback = protocol['lookback_sessions'] as int;
      final bySession = {
        for (final bar in request.bars) bar['session'] as String: bar,
      };
      final rawSignals = data['signals'];
      final rawTrades = data['trades'];
      if (rawSignals is! List ||
          rawSignals.length > request.bars.length ||
          rawTrades is! List ||
          rawTrades.length > rawSignals.length ||
          _count(data['closedTradeCount']) != rawTrades.length) {
        throw _responseError;
      }
      final signals = <Rebound25Signal>[];
      final signalMap = <String, Map<String, dynamic>>{};
      for (final value in rawSignals) {
        final signal = _object(value);
        final session = _date(signal['session']);
        final bar = bySession[session];
        final decision = _instant(signal['decisionAt']);
        if (bar == null ||
            signalMap.containsKey(session) ||
            decision != _instant(bar['availableAt']) ||
            signal['referenceSessionCount'] != lookback ||
            !const {
              'next_open_simulated_entry',
              'volume_or_participation_filter',
              'confirmation_not_available_after_breach',
              'confirmation_volume_or_participation_filter',
              'next_session_unavailable',
              'confirmation_not_available_before_next_open',
              'rebound_confirmation_expired',
              'rebound_confirmation_unavailable_at_end',
            }.contains(signal['outcome'])) {
          throw _responseError;
        }
        _number(signal['priorLow'], positive: true);
        _sameNumber(signal['breachClose'], bar['close'] as num);
        _sameNumber(
          signal['confirmationThreshold'],
          (bar['close'] as num) *
              (1 + (protocol['min_rebound_pct'] as num) / 100),
        );
        if (signal['relativeVolume'] != null) {
          _number(signal['relativeVolume'], nonnegative: true);
        }
        String? confirmation;
        if (signal['confirmationSession'] != null) {
          confirmation = _date(signal['confirmationSession']);
          final confirmBar = bySession[confirmation];
          if (confirmBar == null ||
              confirmation.compareTo(session) <= 0 ||
              _instant(signal['confirmationDecisionAt']) !=
                  _instant(confirmBar['availableAt'])) {
            throw _responseError;
          }
          _sameNumber(signal['confirmationClose'], confirmBar['close'] as num);
        }
        signalMap[session] = signal;
        signals.add(
          Rebound25Signal(
            session: session,
            outcome: signal['outcome'] as String,
            decisionAt: decision,
            confirmationSession: confirmation,
          ),
        );
      }
      var pnl = 0.0, commissions = 0.0, priceCosts = 0.0;
      var exposedSessions = 0;
      final tradedSignals = <String>{};
      String? lastExit;
      for (final value in rawTrades) {
        final trade = _object(value);
        final signal = signalMap[trade['signalSession']];
        final entry = _date(trade['entrySession']);
        final exit = _date(trade['exitSession']);
        final entryBar = bySession[entry], exitBar = bySession[exit];
        final confirmation = _date(trade['confirmationSession']);
        if (signal == null ||
            signal['outcome'] != 'next_open_simulated_entry' ||
            signal['confirmationSession'] != confirmation ||
            !tradedSignals.add(trade['signalSession'] as String) ||
            entryBar == null ||
            exitBar == null ||
            entry.compareTo(confirmation) <= 0 ||
            exit.compareTo(entry) < 0 ||
            (lastExit != null && entry.compareTo(lastExit) <= 0) ||
            _instant(trade['entryAt']) != _instant(entryBar['openAt']) ||
            _instant(trade['decisionAt']) !=
                _instant(signal['confirmationDecisionAt']) ||
            _instant(trade['confirmationDecisionAt']) !=
                _instant(signal['confirmationDecisionAt']) ||
            !_instant(trade['confirmationDecisionAt'])
                .isAfter(_instant(trade['breachDecisionAt'])) ||
            !_instant(trade['entryAt'])
                .isAfter(_instant(trade['decisionAt'])) ||
            _instant(trade['breachDecisionAt']) !=
                _instant(signal['decisionAt']) ||
            _instant(trade['exitEvidenceAvailableAt']) !=
                _instant(exitBar['availableAt'])) {
          throw _responseError;
        }
        final held =
            request.bars.indexOf(exitBar) - request.bars.indexOf(entryBar) + 1;
        if (_count(trade['holdingSessions']) != held) throw _responseError;
        _sameNumber(trade['units'], units);
        final entryPrice = _number(trade['entryPrice'], positive: true);
        final exitPrice = _number(trade['exitPrice'], positive: true);
        _sameNumber(entryPrice, (entryBar['open'] as num) * (1 + adverse));
        final entryBase = entryBar['open'] as num;
        final stop = entryBase * (1 - (protocol['stop_loss_pct'] as num) / 100);
        final target =
            entryBase * (1 + (protocol['take_profit_pct'] as num) / 100);
        final opened = exitBar['open'] as num;
        final low = exitBar['low'] as num, high = exitBar['high'] as num;
        late final num exitBase;
        switch (trade['exitReason']) {
          case 'gap_below_stop':
            if (opened > stop) throw _responseError;
            exitBase = opened;
          case 'gap_above_target':
            if (opened < target) throw _responseError;
            exitBase = opened;
          case 'stop_first_ambiguous_daily_bar':
            if (opened <= stop ||
                opened >= target ||
                low > stop ||
                high < target) {
              throw _responseError;
            }
            exitBase = stop;
          case 'stop_loss':
            if (opened <= stop ||
                opened >= target ||
                low > stop ||
                high >= target) {
              throw _responseError;
            }
            exitBase = stop;
          case 'rebound_target':
            if (opened <= stop ||
                opened >= target ||
                low <= stop ||
                high < target) {
              throw _responseError;
            }
            exitBase = target;
          case 'max_holding_sessions':
            if (opened <= stop ||
                opened >= target ||
                low <= stop ||
                high >= target ||
                held < (protocol['max_holding_sessions'] as int)) {
              throw _responseError;
            }
            exitBase = exitBar['close'] as num;
          default:
            throw _responseError;
        }
        _sameNumber(exitPrice, exitBase * (1 - adverse));
        _sameNumber(trade['grossPnl'], (exitBase - entryBase) * units);
        final commission = _number(trade['commissionCost'], nonnegative: true);
        final priceCost = _number(
          trade['spreadAndSlippageCost'],
          nonnegative: true,
        );
        final net = _number(trade['netPnl']);
        _sameNumber(commission, (entryPrice + exitPrice) * units * fee);
        _sameNumber(net, (exitPrice - entryPrice) * units - commission);
        _sameNumber(net, _number(trade['grossPnl']) - priceCost - commission);
        _sameNumber(
          trade['netReturnPct'],
          net / (entryPrice * units * (1 + fee)) * 100,
        );
        pnl += net;
        commissions += commission;
        priceCosts += priceCost;
        exposedSessions += held;
        lastExit = exit;
      }
      _sameNumber(data['totalNetPnl'], pnl);
      final benchmark = _object(data['benchmark']);
      final comparison = _object(data['benchmarkComparison']);
      final accounting = _object(data['strategyAccounting']);
      final first = request.bars[lookback], last = request.bars.last;
      final evaluationCount = request.bars.length - lookback;
      if (benchmark['schema'] != 'athena.synthetic-buy-and-hold-benchmark.v1' ||
          benchmark['evidenceKind'] != 'synthetic_fixture' ||
          benchmark['performanceValidated'] != false ||
          benchmark['positionClosed'] != false ||
          benchmark['evaluationStartSession'] != first['session'] ||
          benchmark['evaluationEndSession'] != last['session'] ||
          _instant(benchmark['entryAt']) != _instant(first['openAt']) ||
          _instant(benchmark['lastMarkAt']) != _instant(last['observedAt']) ||
          _instant(benchmark['lastMarkAvailableAt']) !=
              _instant(last['availableAt']) ||
          _count(benchmark['evaluationSessionCount']) != evaluationCount ||
          _count(benchmark['exposedSessionCount']) != evaluationCount ||
          comparison['identicalConfiguredUnits'] != true ||
          comparison['identicalPerSideCostParameters'] != true ||
          comparison['comparableByInitialCapital'] != false ||
          comparison['comparableByExposure'] != false ||
          comparison['outperformanceClaimed'] != false) {
        throw _responseError;
      }
      _sameNumber(benchmark['units'], units);
      _sameNumber(benchmark['realizedNetPnl'], 0);
      _sameNumber(benchmark['exposureUnitSessions'], evaluationCount * units);
      final costParameters = _object(benchmark['costParameters']);
      for (final field in ['commission_bps', 'spread_bps', 'slippage_bps']) {
        _sameNumber(costParameters[field], protocol[field] as num);
      }
      double terminal(
        Map<String, dynamic> record,
        num entryBase,
        num entryPrice,
      ) {
        final liquid = _object(record['hypotheticalLiquidation']);
        if (liquid['isRealized'] != false) throw _responseError;
        final mark = last['close'] as num;
        final exitPrice = mark * (1 - adverse);
        final entryFee = entryPrice * units * fee,
            exitFee = exitPrice * units * fee;
        _sameNumber(record['entryBasePrice'], entryBase);
        _sameNumber(record['entryPrice'], entryPrice);
        _sameNumber(
          record['entryCapitalRequired'],
          entryPrice * units + entryFee,
        );
        _sameNumber(record['grossMarkToMarketPnl'], (mark - entryBase) * units);
        _sameNumber(
          record['entrySpreadAndSlippageCost'],
          (entryPrice - entryBase) * units,
        );
        _sameNumber(record['entryCommissionCost'], entryFee);
        _sameNumber(
          record['netMarkToMarketPnlBeforeExitCosts'],
          (mark - entryPrice) * units - entryFee,
        );
        _sameNumber(liquid['exitPrice'], exitPrice);
        _sameNumber(liquid['exitCommissionCost'], exitFee);
        _sameNumber(
          liquid['exitSpreadAndSlippageCost'],
          (mark - exitPrice) * units,
        );
        _sameNumber(liquid['totalCommissionCost'], entryFee + exitFee);
        _sameNumber(
          liquid['totalSpreadAndSlippageCost'],
          (entryPrice - entryBase + mark - exitPrice) * units,
        );
        final net = (exitPrice - entryPrice) * units - entryFee - exitFee;
        _sameNumber(liquid['netPnlAfterAllCosts'], net);
        return net.toDouble();
      }

      _sameNumber(benchmark['lastMarkPrice'], last['close'] as num);
      final baselineNet = terminal(
        benchmark,
        first['open'] as num,
        (first['open'] as num) * (1 + adverse),
      );
      var openMtm = 0.0,
          openLiquidation = 0.0,
          openFee = 0.0,
          openPriceCost = 0.0;
      if (data['openPosition'] != null) {
        final open = _object(data['openPosition']);
        final entryBar = bySession[_date(open['entrySession'])];
        final signal = signalMap[open['signalSession']];
        if (entryBar == null ||
            signal == null ||
            signal['outcome'] != 'next_open_simulated_entry' ||
            tradedSignals.contains(open['signalSession']) ||
            (lastExit != null &&
                (entryBar['session'] as String).compareTo(lastExit) <= 0)) {
          throw _responseError;
        }
        final base = entryBar['open'] as num, price = base * (1 + adverse);
        openFee = (price * units * fee).toDouble();
        openPriceCost = ((price - base) * units).toDouble();
        openMtm = (((last['close'] as num) - price) * units - openFee)
            .toDouble();
        _sameNumber(open['entryPrice'], price);
        _sameNumber(open['units'], units);
        _sameNumber(open['entryCommissionCost'], openFee);
        _sameNumber(open['lastClose'], last['close'] as num);
        _sameNumber(open['unrealizedPnlBeforeExitCosts'], openMtm);
        final hypothetical = _object(accounting['openHypotheticalLiquidation']);
        openLiquidation = terminal(
          {
            'entryBasePrice': base,
            'entryPrice': price,
            'entryCapitalRequired': price * units + openFee,
            'grossMarkToMarketPnl': ((last['close'] as num) - base) * units,
            'entrySpreadAndSlippageCost': openPriceCost,
            'entryCommissionCost': openFee,
            'netMarkToMarketPnlBeforeExitCosts': openMtm,
            'hypotheticalLiquidation': hypothetical,
          },
          base,
          price,
        );
        exposedSessions += request.bars.length - request.bars.indexOf(entryBar);
      } else if (accounting['openHypotheticalLiquidation'] != null) {
        throw _responseError;
      }
      _sameNumber(accounting['realizedNetPnl'], pnl);
      _sameNumber(accounting['closedTradeCommissionCost'], commissions);
      _sameNumber(accounting['closedTradeSpreadAndSlippageCost'], priceCosts);
      _sameNumber(accounting['openEntryCommissionCost'], openFee);
      _sameNumber(accounting['openEntrySpreadAndSlippageCost'], openPriceCost);
      _sameNumber(accounting['openNetMarkToMarketPnlBeforeExitCosts'], openMtm);
      _sameNumber(accounting['combinedPnlBeforeOpenExitCosts'], pnl + openMtm);
      _sameNumber(
        accounting['hypotheticalEndLiquidationNetPnlAfterAllCosts'],
        pnl + openLiquidation,
      );
      if (_count(accounting['exposedSessionCount']) != exposedSessions) {
        throw _responseError;
      }
      _sameNumber(accounting['exposureUnitSessions'], exposedSessions * units);
      _sameNumber(
        comparison['markToMarketPnlDifferenceBeforeOpenExitCosts'],
        pnl + openMtm - (benchmark['netMarkToMarketPnlBeforeExitCosts'] as num),
      );
      _sameNumber(
        comparison['hypotheticalLiquidationPnlDifferenceAfterAllCosts'],
        pnl + openLiquidation - baselineNet,
      );
      List<String> warnings(Object? raw) {
        if (raw is! List || raw.isEmpty || raw.length > 30) {
          throw _responseError;
        }
        return raw.map(_text).toList();
      }

      return Rebound25ResearchResult._(
        tradeCount: rawTrades.length,
        totalNetPnl: pnl,
        benchmarkHypotheticalPnl: baselineNet,
        parametersFingerprint: data['parameterFingerprint'] as String,
        resultFingerprint: data['resultFingerprint'] as String,
        instrumentId: request.instrumentId,
        currency: request.currency,
        signals: List.unmodifiable(signals),
        warnings: List.unmodifiable([
          ...warnings(data['warnings']),
          ...warnings(comparison['warnings']),
        ]),
      );
    } catch (_) {
      throw _responseError;
    }
  }
}

/// Authenticated pure simulation transport. Retries of the same Map reuse its snapshot.
class Rebound25ResearchService {
  Rebound25ResearchService({
    String baseUrl = const String.fromEnvironment(
      'ATHENA_BACKEND_URL',
      defaultValue: 'http://127.0.0.1:8000',
    ),
    http.Client? client,
    AuthSession? session,
    this.requestTimeout = const Duration(seconds: 15),
  }) : _baseUrl = _checkedUrl(baseUrl),
       _client = client ?? http.Client(),
       _ownsClient = client == null,
       _session = session ?? AuthSession.instance {
    if (requestTimeout <= Duration.zero)
      throw ArgumentError('Timeout inválido.');
  }
  static const int maxBodyBytes = 2 * 1024 * 1024;
  final String _baseUrl;
  final http.Client _client;
  final bool _ownsClient;
  final AuthSession _session;
  final Duration requestTimeout;
  final _snapshots = Expando<Rebound25ResearchRequest>();
  final Map<String, Future<Rebound25ResearchResult>> _pending = {};
  bool _disposed = false;

  static String _checkedUrl(String value) {
    final uri = Uri.tryParse(value);
    if (uri == null ||
        uri.host.isEmpty ||
        uri.userInfo.isNotEmpty ||
        uri.hasQuery ||
        uri.hasFragment ||
        !(uri.scheme == 'https' ||
            (uri.scheme == 'http' &&
                const {'localhost', '127.0.0.1', '::1'}.contains(uri.host)))) {
      throw ArgumentError('Origen de backend inválido.');
    }
    return value.replaceAll(RegExp(r'/+$'), '');
  }

  Future<Rebound25ResearchResult> run(Map<String, dynamic> request) {
    if (_disposed) return Future.error(StateError('Servicio cerrado.'));
    final token = _session.accessToken, version = _session.authorityVersion;
    if (!_session.isAuthenticated || token == null || token.trim().isEmpty) {
      return Future.error(
        StateError('Inicia sesión para ejecutar la simulación sintética.'),
      );
    }
    final Rebound25ResearchRequest frozen;
    try {
      frozen = _snapshots[request] ??= Rebound25ResearchRequest(request);
    } catch (_) {
      return Future.error(
        const FormatException('Solicitud sintética inválida.'),
      );
    }
    final key = '$version:${frozen.encodedBody}';
    final existing = _pending[key];
    if (existing != null) return existing;
    final future = _run(frozen, token, version);
    _pending[key] = future;
    future.then(
      (_) {
        _pending.remove(key);
      },
      onError: (Object _, StackTrace _) {
        _pending.remove(key);
      },
    );
    return future;
  }

  void _checkAuthority(String token, int version) {
    if (_disposed ||
        !_session.isAuthenticated ||
        _session.accessToken != token ||
        _session.authorityVersion != version)
      throw StateError('La sesión cambió durante la simulación.');
  }

  Future<Rebound25ResearchResult> _run(
    Rebound25ResearchRequest frozen,
    String token,
    int version,
  ) async {
    late http.StreamedResponse response;
    late Uint8List bytes;
    try {
      Future<Uint8List> send() async {
        final request =
            http.Request(
                'POST',
                Uri.parse(
                  '$_baseUrl/api/v1/research/strategies/rebound25/synthetic-backtest',
                ),
              )
              ..followRedirects = false
              ..headers.addAll({
                'Authorization': 'Bearer $token',
                'Content-Type': 'application/json',
              })
              ..body = frozen.encodedBody;
        response = await _client.send(request);
        _checkAuthority(token, version);
        final buffer = BytesBuilder(copy: false);
        await for (final chunk in response.stream) {
          _checkAuthority(token, version);
          if (buffer.length + chunk.length > maxBodyBytes) throw _responseError;
          buffer.add(chunk);
        }
        return buffer.takeBytes();
      }

      bytes = await send().timeout(requestTimeout);
    } catch (_) {
      _checkAuthority(token, version);
      throw StateError('No se pudo completar la simulación sintética.');
    }
    _checkAuthority(token, version);
    if (response.statusCode != 200)
      throw StateError('Simulación sintética no disponible para esta sesión.');
    try {
      final decoded = _object(jsonDecode(utf8.decode(bytes)));
      return Rebound25ResearchResult._parse(_object(decoded['data']), frozen);
    } catch (_) {
      throw _responseError;
    }
  }

  void dispose() {
    _disposed = true;
    if (_ownsClient) _client.close();
  }
}
