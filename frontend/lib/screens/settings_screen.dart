import 'package:flutter/material.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'package:threadbot/services/api_service.dart';

class SettingsScreen extends StatefulWidget {
  const SettingsScreen({super.key});

  @override
  State<SettingsScreen> createState() => _SettingsScreenState();
}

class _SettingsScreenState extends State<SettingsScreen> {
  final _apiUrlController = TextEditingController();
  final _apiKeyController = TextEditingController();
  final _modelController = TextEditingController();
  bool _isLoading = true;
  bool _isSaving = false;

  @override
  void initState() {
    super.initState();
    _loadSettings();
  }

  Future<void> _loadSettings() async {
    setState(() => _isLoading = true);
    try {
      final prefs = await SharedPreferences.getInstance();

      // Try backend first, fallback to local
      try {
        final settings = await ApiService().getSettings();
        _apiUrlController.text = settings['llm_api_url'] as String? ?? '';
        _modelController.text = settings['llm_model'] as String? ?? '';
      } catch (_) {
        _apiUrlController.text = prefs.getString('llm_api_url') ?? 'http://localhost:11434/v1';
        _modelController.text = prefs.getString('llm_model') ?? 'llama3.1';
      }

      _apiKeyController.text = prefs.getString('llm_api_key') ?? '';

      // Sync to local storage
      await prefs.setString('llm_api_url', _apiUrlController.text);
      await prefs.setString('llm_model', _modelController.text);
    } catch (_) {}

    if (mounted) setState(() => _isLoading = false);
  }

  Future<void> _saveSettings() async {
    setState(() => _isSaving = true);
    try {
      final api = ApiService();
      await api.saveSettings(
        apiUrl: _apiUrlController.text,
        apiKey: _apiKeyController.text,
        model: _modelController.text,
      );
      await api.sendSettingsToBackend(
        apiUrl: _apiUrlController.text,
        apiKey: _apiKeyController.text,
        model: _modelController.text,
      );

      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(
            content: const Text('Settings saved'),
            backgroundColor: const Color(0xFF16161E),
            behavior: SnackBarBehavior.floating,
            shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(10)),
          ),
        );
      }
    } finally {
      if (mounted) setState(() => _isSaving = false);
    }
  }

  @override
  void dispose() {
    _apiUrlController.dispose();
    _apiKeyController.dispose();
    _modelController.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: const Color(0xFF0D0D12),
      appBar: AppBar(
        backgroundColor: const Color(0xFF0D0D12),
        title: const Text(
          'Settings',
          style: TextStyle(fontSize: 18, fontWeight: FontWeight.w600),
        ),
        leading: IconButton(
          icon: const Icon(Icons.arrow_back_rounded),
          onPressed: () => Navigator.pop(context),
        ),
        actions: [
          Padding(
            padding: const EdgeInsets.only(right: 8),
            child: FilledButton(
              onPressed: _isSaving ? null : _saveSettings,
              style: FilledButton.styleFrom(
                backgroundColor: const Color(0xFF8B5CF6),
                foregroundColor: Colors.white,
                shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(10)),
              ),
              child: _isSaving
                  ? const SizedBox(
                      width: 16,
                      height: 16,
                      child: CircularProgressIndicator(strokeWidth: 2, color: Colors.white),
                    )
                  : const Text('Save'),
            ),
          ),
        ],
      ),
      body: _isLoading
          ? const Center(
              child: CircularProgressIndicator(
                valueColor: AlwaysStoppedAnimation(Color(0xFF8B5CF6)),
              ),
            )
          : SingleChildScrollView(
              padding: const EdgeInsets.all(24),
              child: Center(
                child: ConstrainedBox(
                  constraints: const BoxConstraints(maxWidth: 600),
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      _buildSection(
                        'LLM Configuration',
                        'Configure the AI model backend',
                        Icons.psychology_outlined,
                        [
                          _buildField(
                            controller: _apiUrlController,
                            label: 'API URL',
                            hint: 'http://localhost:11434/v1',
                            icon: Icons.link_rounded,
                          ),
                          const SizedBox(height: 16),
                          _buildField(
                            controller: _apiKeyController,
                            label: 'API Key',
                            hint: 'Leave blank for Ollama',
                            icon: Icons.key_rounded,
                            obscure: true,
                          ),
                          const SizedBox(height: 16),
                          _buildField(
                            controller: _modelController,
                            label: 'Model',
                            hint: 'llama3.1',
                            icon: Icons.smart_toy_outlined,
                          ),
                        ],
                      ),
                      const SizedBox(height: 32),
                      _buildSection(
                        'About',
                        'ThreadBot v1.0',
                        Icons.info_outline_rounded,
                        [
                          Container(
                            padding: const EdgeInsets.all(16),
                            decoration: BoxDecoration(
                              borderRadius: BorderRadius.circular(12),
                              color: Colors.white.withValues(alpha: 0.02),
                              border: Border.all(color: Colors.white.withValues(alpha: 0.06)),
                            ),
                            child: Column(
                              crossAxisAlignment: CrossAxisAlignment.start,
                              children: [
                                Row(
                                  children: [
                                    Container(
                                      width: 40,
                                      height: 40,
                                      decoration: BoxDecoration(
                                        borderRadius: BorderRadius.circular(10),
                                        gradient: const LinearGradient(
                                          colors: [Color(0xFF8B5CF6), Color(0xFF6366F1)],
                                        ),
                                      ),
                                      child: const Icon(Icons.auto_awesome, size: 20, color: Colors.white),
                                    ),
                                    const SizedBox(width: 12),
                                    const Column(
                                      crossAxisAlignment: CrossAxisAlignment.start,
                                      children: [
                                        Text(
                                          'ThreadBot',
                                          style: TextStyle(fontSize: 16, fontWeight: FontWeight.w600),
                                        ),
                                        Text(
                                          'Temporal-powered AI chatbot',
                                          style: TextStyle(fontSize: 12, color: Color(0xFF71717A)),
                                        ),
                                      ],
                                    ),
                                  ],
                                ),
                                const SizedBox(height: 16),
                                const _FeatureRow(icon: Icons.chat_bubble_outline, text: 'Thread-based conversations'),
                                const _FeatureRow(icon: Icons.webhook_outlined, text: 'Temporal workflow orchestration'),
                                const _FeatureRow(icon: Icons.api_outlined, text: 'OpenAI-compatible API support'),
                                const _FeatureRow(icon: Icons.cloud_outlined, text: 'Docker & Kubernetes ready'),
                              ],
                            ),
                          ),
                        ],
                      ),
                    ],
                  ),
                ),
              ),
            ),
    );
  }

  Widget _buildSection(String title, String subtitle, IconData icon, List<Widget> children) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Row(
          children: [
            Icon(icon, size: 20, color: const Color(0xFF8B5CF6)),
            const SizedBox(width: 8),
            Text(title, style: const TextStyle(fontSize: 16, fontWeight: FontWeight.w600)),
          ],
        ),
        const SizedBox(height: 4),
        Text(subtitle, style: TextStyle(fontSize: 13, color: Colors.white.withValues(alpha: 0.4))),
        const SizedBox(height: 16),
        ...children,
      ],
    );
  }

  Widget _buildField({
    required TextEditingController controller,
    required String label,
    required String hint,
    required IconData icon,
    bool obscure = false,
  }) {
    return TextField(
      controller: controller,
      obscureText: obscure,
      style: const TextStyle(fontSize: 14),
      decoration: InputDecoration(
        labelText: label,
        hintText: hint,
        prefixIcon: Icon(icon, size: 18, color: const Color(0xFF71717A)),
        labelStyle: TextStyle(color: Colors.white.withValues(alpha: 0.5)),
        enabledBorder: OutlineInputBorder(
          borderRadius: BorderRadius.circular(12),
          borderSide: BorderSide(color: Colors.white.withValues(alpha: 0.08)),
        ),
        focusedBorder: OutlineInputBorder(
          borderRadius: BorderRadius.circular(12),
          borderSide: const BorderSide(color: Color(0xFF8B5CF6), width: 1.5),
        ),
        filled: true,
        fillColor: const Color(0xFF16161E),
      ),
    );
  }
}

class _FeatureRow extends StatelessWidget {
  final IconData icon;
  final String text;

  const _FeatureRow({required this.icon, required this.text});

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.only(bottom: 8),
      child: Row(
        children: [
          Icon(icon, size: 14, color: const Color(0xFF8B5CF6)),
          const SizedBox(width: 8),
          Text(text, style: const TextStyle(fontSize: 13, color: Color(0xFFA1A1AA))),
        ],
      ),
    );
  }
}
