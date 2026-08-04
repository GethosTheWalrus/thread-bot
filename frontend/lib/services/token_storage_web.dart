import 'package:web/web.dart' as web;

const _key = 'threadbot.auth.token';

Future<String?> readToken() async => web.window.localStorage.getItem(_key);
Future<void> writeToken(String token) async {
  web.window.localStorage.setItem(_key, token);
}

Future<void> clearToken() async {
  web.window.localStorage.removeItem(_key);
}
