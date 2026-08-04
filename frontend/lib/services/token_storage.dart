import 'token_storage_stub.dart'
    if (dart.library.html) 'token_storage_web.dart';

Future<String?> readStoredToken() => readToken();
Future<void> storeToken(String token) => writeToken(token);
Future<void> clearStoredToken() => clearToken();
