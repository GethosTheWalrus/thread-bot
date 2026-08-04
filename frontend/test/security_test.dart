import 'package:flutter_test/flutter_test.dart';
import 'package:threadbot/models/security.dart';

void main() {
  test('parses local and admin token security modes', () {
    expect(SecuritySettings.fromJson({'mode': 'local'}).tokenMode, isFalse);
    expect(
      SecuritySettings.fromJson({'mode': 'admin_token'}).tokenMode,
      isTrue,
    );
  });

  test('parses a one-time token from a mode update', () {
    final update = SecurityModeUpdate.fromJson({
      'mode': 'admin_token',
      'token': 'one-time-token',
    });
    expect(update.settings.tokenMode, isTrue);
    expect(update.token, 'one-time-token');
  });
}
