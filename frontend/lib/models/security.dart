class SecuritySettings {
  final String mode;

  const SecuritySettings({required this.mode});

  bool get tokenMode => mode == 'admin_token';

  factory SecuritySettings.fromJson(Map<String, dynamic> json) {
    final value =
        json['mode'] ??
        json['security_mode'] ??
        (json['token_enabled'] == true ? 'admin_token' : 'local');
    return SecuritySettings(mode: value.toString());
  }
}

class SecurityModeUpdate {
  final SecuritySettings settings;
  final String? token;

  const SecurityModeUpdate({required this.settings, this.token});

  factory SecurityModeUpdate.fromJson(Map<String, dynamic> json) {
    final settingsJson = json['settings'] is Map
        ? Map<String, dynamic>.from(json['settings'] as Map)
        : json;
    return SecurityModeUpdate(
      settings: SecuritySettings.fromJson(settingsJson),
      token: (json['token'] ?? json['new_token'] ?? json['auth_token'])
          ?.toString(),
    );
  }
}
