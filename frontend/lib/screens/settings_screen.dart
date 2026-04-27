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
  final _contextWindowController = TextEditingController();
  final _preserveRecentController = TextEditingController();
  double _compactionThreshold = 0.75;

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

      final localApiUrl = prefs.getString('llm_api_url');
      final localModel = prefs.getString('llm_model');

      _apiKeyController.text = prefs.getString('llm_api_key') ?? '';
      _contextWindowController.text =
          (prefs.getInt('llm_context_window') ?? 8192).toString();
      _preserveRecentController.text =
          (prefs.getInt('llm_preserve_recent') ?? 10).toString();
      _compactionThreshold =
          prefs.getDouble('llm_compaction_threshold') ?? 0.75;

      if (localApiUrl != null && localApiUrl.isNotEmpty && localModel != null && localModel.isNotEmpty) {
        _apiUrlController.text = localApiUrl;
        _modelController.text = localModel;
      } else {
        try {
          final settings = await ApiService().getSettings();
          _apiUrlController.text = settings['llm_api_url'] as String? ?? '';
          _modelController.text = settings['llm_model'] as String? ?? '';
          _contextWindowController.text =
              (settings['llm_context_window'] ?? 8192).toString();
          _preserveRecentController.text =
              (settings['llm_preserve_recent'] ?? 10).toString();
          _compactionThreshold =
              (settings['llm_compaction_threshold'] as num?)?.toDouble() ?? 0.75;
        } catch (_) {
          _apiUrlController.text = '';
          _modelController.text = 'llama3.1';
        }
      }
    } catch (_) {}

    if (mounted) setState(() => _isLoading = false);
  }

  Future<void> _saveSettings() async {
    setState(() => _isSaving = true);
    try {
      final prefs = await SharedPreferences.getInstance();
      final api = ApiService();

      await api.saveSettings(
        apiUrl: _apiUrlController.text,
        apiKey: _apiKeyController.text,
        model: _modelController.text,
      );

      final contextWindow = int.tryParse(_contextWindowController.text) ?? 8192;
      final preserveRecent = int.tryParse(_preserveRecentController.text) ?? 10;

      await prefs.setInt('llm_context_window', contextWindow);
      await prefs.setDouble('llm_compaction_threshold', _compactionThreshold);
      await prefs.setInt('llm_preserve_recent', preserveRecent);

      await api.sendSettingsToBackend(
        apiUrl: _apiUrlController.text,
        apiKey: _apiKeyController.text,
        model: _modelController.text,
      );

      // Also send context management settings to backend
      try {
        await api.updateContextSettings(
          contextWindow: contextWindow,
          compactionThreshold: _compactionThreshold,
          preserveRecent: preserveRecent,
        );
      } catch (_) {}

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
    _contextWindowController.dispose();
    _preserveRecentController.dispose();
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
                        'Context Management',
                        'Control how long conversations are handled',
                        Icons.compress_rounded,
                        [
                          _buildField(
                            controller: _contextWindowController,
                            label: 'Context Window (tokens)',
                            hint: '8192',
                            icon: Icons.token_outlined,
                            keyboardType: TextInputType.number,
                          ),
                          const SizedBox(height: 24),
                          _buildThresholdSlider(),
                          const SizedBox(height: 24),
                          _buildField(
                            controller: _preserveRecentController,
                            label: 'Preserve Recent Messages',
                            hint: '10',
                            icon: Icons.history_rounded,
                            keyboardType: TextInputType.number,
                          ),
                          const SizedBox(height: 12),
                          Container(
                            padding: const EdgeInsets.all(12),
                            decoration: BoxDecoration(
                              borderRadius: BorderRadius.circular(10),
                              color: const Color(0xFF8B5CF6).withValues(alpha: 0.06),
                              border: Border.all(
                                color: const Color(0xFF8B5CF6).withValues(alpha: 0.15),
                              ),
                            ),
                            child: Row(
                              children: [
                                const Icon(Icons.info_outline_rounded,
                                    size: 16, color: Color(0xFF8B5CF6)),
                                const SizedBox(width: 8),
                                Expanded(
                                  child: Text(
                                    'When estimated token usage exceeds ${(_compactionThreshold * 100).round()}% '
                                    'of the context window, older messages are summarized automatically.',
                                    style: TextStyle(
                                      fontSize: 12,
                                      color: Colors.white.withValues(alpha: 0.5),
                                    ),
                                  ),
                                ),
                              ],
                            ),
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
                                const _FeatureRow(icon: Icons.layers_outlined, text: 'Dockerized MCP tool servers'),
                                const _FeatureRow(icon: Icons.compress_rounded, text: 'Automatic context compaction'),
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

  Widget _buildThresholdSlider() {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Row(
          children: [
            const Icon(Icons.tune_rounded, size: 18, color: Color(0xFF71717A)),
            const SizedBox(width: 8),
            Text(
              'Compaction Threshold',
              style: TextStyle(
                fontSize: 14,
                color: Colors.white.withValues(alpha: 0.5),
              ),
            ),
            const Spacer(),
            Container(
              padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 4),
              decoration: BoxDecoration(
                borderRadius: BorderRadius.circular(8),
                color: const Color(0xFF8B5CF6).withValues(alpha: 0.15),
              ),
              child: Text(
                '${(_compactionThreshold * 100).round()}%',
                style: const TextStyle(
                  fontSize: 13,
                  fontWeight: FontWeight.w600,
                  color: Color(0xFF8B5CF6),
                ),
              ),
            ),
          ],
        ),
        const SizedBox(height: 8),
        SliderTheme(
          data: SliderThemeData(
            activeTrackColor: const Color(0xFF8B5CF6),
            inactiveTrackColor: Colors.white.withValues(alpha: 0.1),
            thumbColor: const Color(0xFF8B5CF6),
            overlayColor: const Color(0xFF8B5CF6).withValues(alpha: 0.1),
            trackHeight: 4,
          ),
          child: Slider(
            value: _compactionThreshold,
            min: 0.5,
            max: 0.95,
            divisions: 9,
            onChanged: (v) => setState(() => _compactionThreshold = v),
          ),
        ),
        Row(
          mainAxisAlignment: MainAxisAlignment.spaceBetween,
          children: [
            Text('50%', style: TextStyle(fontSize: 11, color: Colors.white.withValues(alpha: 0.3))),
            Text('95%', style: TextStyle(fontSize: 11, color: Colors.white.withValues(alpha: 0.3))),
          ],
        ),
      ],
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
    TextInputType? keyboardType,
  }) {
    return TextField(
      controller: controller,
      obscureText: obscure,
      keyboardType: keyboardType,
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
