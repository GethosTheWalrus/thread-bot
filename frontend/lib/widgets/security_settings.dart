import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:threadbot/models/security.dart';
import 'package:threadbot/services/api_service.dart';
import 'package:threadbot/services/token_storage.dart';

class SecuritySettingsSection extends StatefulWidget {
  final ApiService api;
  const SecuritySettingsSection({super.key, required this.api});

  @override
  State<SecuritySettingsSection> createState() =>
      _SecuritySettingsSectionState();
}

class _SecuritySettingsSectionState extends State<SecuritySettingsSection> {
  SecuritySettings? _settings;
  String? _token;
  bool _loading = true;
  bool _busy = false;
  bool _revealed = false;
  String? _error;

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    try {
      final values = await Future.wait([
        widget.api.getSecuritySettings(),
        readStoredToken(),
      ]);
      if (!mounted) return;
      setState(() {
        _settings = values[0] as SecuritySettings;
        _token = values[1] as String?;
        _loading = false;
      });
    } catch (error) {
      if (mounted)
        setState(() {
          _loading = false;
          _error = '$error';
        });
    }
  }

  Future<void> _setTokenMode(bool enabled) async {
    setState(() => _busy = true);
    try {
      final result = await widget.api.setSecurityMode(
        enabled ? 'admin_token' : 'local',
      );
      if (!enabled) {
        await clearStoredToken();
        if (mounted)
          setState(() {
            _token = null;
            _revealed = false;
            _settings = result.settings;
          });
      } else {
        if (result.token != null && result.token!.isNotEmpty) {
          await storeToken(result.token!);
          if (mounted)
            setState(() {
              _token = result.token;
              _settings = result.settings;
            });
          if (mounted) await _showToken(result.token!);
        } else if (mounted)
          setState(() => _settings = result.settings);
      }
    } catch (error) {
      if (mounted) setState(() => _error = '$error');
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  Future<void> _showToken(String token) async {
    await showDialog<void>(
      context: context,
      builder: (context) => AlertDialog(
        title: const Text('Save your new token'),
        content: SelectableText(token),
        actions: [
          TextButton.icon(
            onPressed: () async {
              await Clipboard.setData(ClipboardData(text: token));
              if (context.mounted) Navigator.pop(context);
            },
            icon: const Icon(Icons.copy_outlined),
            label: const Text('Copy and close'),
          ),
          TextButton(
            onPressed: () => Navigator.pop(context),
            child: const Text('Close'),
          ),
        ],
      ),
    );
  }

  Future<void> _copyToken() async {
    if (_token == null) return;
    await Clipboard.setData(ClipboardData(text: _token!));
    if (mounted)
      ScaffoldMessenger.of(
        context,
      ).showSnackBar(const SnackBar(content: Text('Token copied')));
  }

  @override
  Widget build(BuildContext context) {
    if (_loading) return const Center(child: CircularProgressIndicator());
    if (_error != null && _settings == null)
      return Text('Could not load security settings: $_error');
    final tokenMode = _settings?.tokenMode ?? false;
    return Card(
      child: Padding(
        padding: const EdgeInsets.all(20),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            const Text(
              'Authentication',
              style: TextStyle(fontSize: 17, fontWeight: FontWeight.w600),
            ),
            const SizedBox(height: 8),
            const Text(
              'Token mode protects this server with a browser session. The server cannot recover a token after it is created. This browser stores the token so it can be revealed later; browser storage can be read by code running on this site. Tokens entered in another browser cannot be revealed here.',
            ),
            const SizedBox(height: 12),
            SwitchListTile.adaptive(
              contentPadding: EdgeInsets.zero,
              value: tokenMode,
              onChanged: _busy ? null : _setTokenMode,
              title: const Text('Enable token mode'),
              subtitle: Text(
                tokenMode ? 'Token mode is enabled.' : 'Local mode is enabled.',
              ),
            ),
            if (_token != null) ...[
              const SizedBox(height: 8),
              Row(
                children: [
                  Expanded(
                    child: Text(
                      _revealed ? _token! : '••••••••••••••••',
                      overflow: TextOverflow.ellipsis,
                    ),
                  ),
                  IconButton(
                    tooltip: _revealed ? 'Hide token' : 'Reveal token',
                    onPressed: () => setState(() => _revealed = !_revealed),
                    icon: Icon(
                      _revealed ? Icons.visibility_off : Icons.visibility,
                    ),
                  ),
                  IconButton(
                    tooltip: 'Copy token',
                    onPressed: _copyToken,
                    icon: const Icon(Icons.copy_outlined),
                  ),
                ],
              ),
            ],
            if (_error != null)
              Text(
                _error!,
                style: TextStyle(color: Theme.of(context).colorScheme.error),
              ),
          ],
        ),
      ),
    );
  }
}
