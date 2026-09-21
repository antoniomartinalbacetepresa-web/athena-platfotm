import 'dart:async';
import 'dart:convert';

import 'package:app/features/auth/models/auth_account.dart';
import 'package:app/features/auth/services/athena_auth_service.dart';
import 'package:app/features/auth/services/auth_session.dart';
import 'package:app/features/auth/services/auth_token_store.dart';
import 'package:app/features/market/models/market_quote.dart';
import 'package:app/features/market/repositories/market_repository.dart';
import 'package:app/features/portfolio/services/authenticated_portfolio_service.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';

class _MemoryTokenStore implements AuthTokenStore {
  String? token;
  @override Future<String?> readAccessToken() async => token;
  @override Future<void> writeAccessToken(String accessToken) async { token=accessToken; }
  @override Future<void> deleteAccessToken() async { token=null; }
}
class _MarketRepository implements MarketRepository { _MarketRepository(this.quote); final MarketQuote quote; final requestedSymbols=<String>[]; @override Future<MarketQuote> getQuote(String symbol) async {requestedSymbols.add(symbol);return quote;} }

void main(){
  AuthAccount account({int id=7,String email='user@example.com'})=>AuthAccount(id:id,email:email,displayName:'Athena User',isActive:true,createdAt:DateTime.parse('2026-09-10T10:00:00Z'),updatedAt:DateTime.parse('2026-09-10T10:00:00Z'));
  MarketQuote quote({String symbol='AAPL',String? exchange='NASDAQ',String? provider='yahoo_finance',double price=200,DateTime? observedAt,DateTime? retrievedAt}){final observed=observedAt??DateTime.parse('2026-09-15T16:00:00Z');return MarketQuote(symbol:symbol,companyName:'Apple Inc.',currentPrice:price,change:1,changePercentage:.5,exchange:exchange,currency:'USD',updatedAt:observed,sourceProvider:provider,retrievedAt:retrievedAt??observed.add(const Duration(seconds:2)));}
  http.Response portfolioResponse({double? averagePurchasePrice=160}){final cost=averagePurchasePrice==null?'':',"averagePurchasePrice":$averagePurchasePrice';return http.Response('{"data":{"positions":[{"id":3,"symbol":"AAPL","exchange":"NASDAQ","quantity":4.5$cost,"createdAt":"2026-09-10T10:00:00Z","updatedAt":"2026-09-10T10:01:00Z"}],"positionCount":1}}',200);}

  test('guest session is rejected before any network call',()async{final session=AuthSession.forTesting(_MemoryTokenStore());var called=false;final service=AuthenticatedPortfolioService(baseUrl:'http://athena.local',client:MockClient((_)async{called=true;return http.Response('{}',500);}),session:session);await expectLater(service.loadPositions(),throwsStateError);expect(called,isFalse);});
  test('load sends bearer token and parses owner-visible encrypted cost basis',()async{final session=AuthSession.forTesting(_MemoryTokenStore());session.establish(accessToken:'signed.jwt.token',account:account());late http.Request captured;final service=AuthenticatedPortfolioService(baseUrl:'http://athena.local',client:MockClient((r)async{captured=r;return portfolioResponse(averagePurchasePrice:187.25);}),session:session);final positions=await service.loadPositions();expect(captured.headers['Authorization'],'Bearer signed.jwt.token');expect(positions.single.averagePurchasePrice,187.25);});
  test('valued positions join authenticated holdings with provenance',()async{final session=AuthSession.forTesting(_MemoryTokenStore());session.establish(accessToken:'signed.jwt.token',account:account());final market=_MarketRepository(quote());final service=AuthenticatedPortfolioService(baseUrl:'http://athena.local',client:MockClient((_)async=>portfolioResponse()),session:session);final positions=await service.loadValuedPositions(marketRepository:market);expect(positions.single.currentValue,900);expect(positions.single.profitLoss,180);expect(market.requestedSymbols,['AAPL']);});
  test('upsert never sends client owner or trading authority',()async{final session=AuthSession.forTesting(_MemoryTokenStore());session.establish(accessToken:'signed.jwt.token',account:account());late http.Request captured;final service=AuthenticatedPortfolioService(baseUrl:'http://athena.local',client:MockClient((r)async{captured=r;return http.Response('{"data":{"id":4,"symbol":"MSFT","exchange":"NASDAQ","quantity":2.0,"averagePurchasePrice":405.5,"createdAt":"2026-09-10T10:00:00Z","updatedAt":"2026-09-10T10:00:00Z"}}',200);}),session:session);await service.upsertPosition(symbol:' msft ',exchange:' nasdaq ',quantity:2,averagePurchasePrice:405.5);final body=jsonDecode(captured.body) as Map<String,dynamic>;expect(body.containsKey('ownerUserId'),isFalse);expect(body.containsKey('automaticTrading'),isFalse);});

  test('stale Portfolio rejection cannot revoke replacement owner',()async{
    final store=_MemoryTokenStore(); final session=AuthSession.forTesting(store); await session.establishPersisted(accessToken:'owner-a.jwt',account:account());
    final pending=Completer<http.Response>(); late http.Request captured;
    final service=AuthenticatedPortfolioService(baseUrl:'http://athena.local',client:MockClient((request){captured=request;return pending.future;}),session:session);
    final oldRequest=service.loadPositions(); await Future<void>.delayed(Duration.zero); expect(captured.headers['Authorization'],'Bearer owner-a.jwt');
    await session.establishPersisted(accessToken:'owner-b.jwt',account:account(id:23,email:'replacement@example.com'));
    pending.complete(http.Response('{"detail":"old credential rejected"}',401));
    await expectLater(oldRequest,throwsA(isA<AuthSessionRejectedException>()));
    expect(session.isAuthenticated,isTrue); expect(session.accessToken,'owner-b.jwt'); expect(session.account?.id,23); expect(store.token,'owner-b.jwt');
  });

  test('current Portfolio rejection revokes current owner and durable token',()async{
    final store=_MemoryTokenStore(); final session=AuthSession.forTesting(store); await session.establishPersisted(accessToken:'current.jwt',account:account());
    final service=AuthenticatedPortfolioService(baseUrl:'http://athena.local',client:MockClient((_)async=>http.Response('{"detail":"rejected"}',403)),session:session);
    await expectLater(service.loadPositions(),throwsA(isA<AuthSessionRejectedException>().having((e)=>e.statusCode,'statusCode',403)));
    expect(session.isAuthenticated,isFalse); expect(session.accessToken,isNull); expect(store.token,isNull);
  });
}
