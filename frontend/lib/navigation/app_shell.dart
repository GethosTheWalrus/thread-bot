import 'package:flutter/material.dart';
import 'package:threadbot/services/autonomy_api.dart';
import 'package:threadbot/services/token_storage.dart';

class AuthScreen extends StatefulWidget {
  final AutonomyApiService api;
  const AuthScreen({super.key, required this.api});
  @override
  State<AuthScreen> createState() => _AuthState();
}

class _AuthState extends State<AuthScreen> {
  final controller = TextEditingController();
  bool busy = true;
  String? error;

  @override
  void initState() {
    super.initState();
    _restoreSession();
  }

  Future<void> _restoreSession() async {
    final token = await readStoredToken();
    if (token == null || token.isEmpty) {
      if (mounted) setState(() => busy = false);
      return;
    }
    try {
      await widget.api.createSession(token);
      if (mounted) Navigator.pushReplacementNamed(context, '/');
    } catch (_) {
      await clearStoredToken();
      if (mounted) setState(() => busy = false);
    }
  }

  @override
  void dispose() {
    controller.dispose();
    super.dispose();
  }

  Future<void> submit() async {
    setState(() => busy = true);
    try {
      await widget.api.createSession(controller.text);
      await storeToken(controller.text);
      if (mounted) Navigator.pushReplacementNamed(context, '/');
    } catch (e) {
      if (mounted) setState(() => error = '$e');
    } finally {
      if (mounted) setState(() => busy = false);
    }
  }

  @override
  Widget build(BuildContext context) => Scaffold(
    body: Center(
      child: ConstrainedBox(
        constraints: const BoxConstraints(maxWidth: 420),
        child: Card(
          child: Padding(
            padding: const EdgeInsets.all(24),
            child: Column(
              mainAxisSize: MainAxisSize.min,
              children: [
                const Icon(Icons.lock_outline, size: 42),
                const SizedBox(height: 16),
                Text(
                  'Admin sign in',
                  style: Theme.of(context).textTheme.headlineSmall,
                ),
                const SizedBox(height: 16),
                TextField(
                  controller: controller,
                  obscureText: true,
                  decoration: const InputDecoration(labelText: 'Admin token'),
                ),
                if (error != null)
                  Text(
                    error!,
                    style: TextStyle(
                      color: Theme.of(context).colorScheme.error,
                    ),
                  ),
                const SizedBox(height: 16),
                FilledButton(
                  onPressed: busy ? null : submit,
                  child: Text(busy ? 'Signing in…' : 'Continue'),
                ),
              ],
            ),
          ),
        ),
      ),
    ),
  );
}
