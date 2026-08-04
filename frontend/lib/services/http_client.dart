import 'package:http/http.dart' as http;
import 'package:flutter/foundation.dart';
import 'http_client_stub.dart' if (dart.library.html) 'http_client_web.dart';

http.Client createHttpClient() => createPlatformHttpClient();

class UnauthorizedClient extends http.BaseClient {
  final http.Client _inner;
  final VoidCallback? onUnauthorized;

  UnauthorizedClient(this._inner, this.onUnauthorized);

  @override
  Future<http.StreamedResponse> send(http.BaseRequest request) async {
    final response = await _inner.send(request);
    if (response.statusCode == 401) onUnauthorized?.call();
    return response;
  }

  @override
  void close() => _inner.close();
}
