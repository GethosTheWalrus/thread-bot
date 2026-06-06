import 'package:flutter/material.dart';
import 'package:threadbot/services/api_service.dart';
import 'package:threadbot/widgets/threadbot_avatar.dart';

class SettingsScreen extends StatefulWidget {
  const SettingsScreen({super.key});

  @override
  State<SettingsScreen> createState() => _SettingsScreenState();
}

class _SettingsScreenState extends State<SettingsScreen> {
  final _api = ApiService();
  final _apiUrlController = TextEditingController();
  final _apiKeyController = TextEditingController();
  final _modelController = TextEditingController();
  final _imageApiUrlController = TextEditingController();
  final _imageModelController = TextEditingController();
  final _comfyuiApiUrlController = TextEditingController();
  final _comfyuiOutputNodeController = TextEditingController();
  final _comfyuiNegativePromptController = TextEditingController();
  final _comfyuiWidthController = TextEditingController();
  final _comfyuiHeightController = TextEditingController();
  final _comfyuiStepsController = TextEditingController();
  final _comfyuiCfgController = TextEditingController();
  final _comfyuiSamplerController = TextEditingController();
  final _comfyuiSchedulerController = TextEditingController();
  final _comfyuiSeedController = TextEditingController();
  final _comfyuiWorkflowController = TextEditingController();
  final _publicBaseUrlController = TextEditingController();
  final _maxIterationsController = TextEditingController();
  final _contextWindowController = TextEditingController();
  final _preserveRecentController = TextEditingController();
  final _toolResultMaxCharsController = TextEditingController();
  final _discordTokenController = TextEditingController();
  final _discordGuildController = TextEditingController();
  final _discordChannelController = TextEditingController();
  final _discordPollController = TextEditingController();
  double _compactionThreshold = 0.75;
  bool _imageGenerationEnabled = false;
  String _imageProvider = 'auto';
  bool _discordEnabled = false;
  List<Map<String, dynamic>> _discordServers = [];
  bool _isLoadingDiscordServers = false;

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
      final settings = await _api.getSettings();
      _apiUrlController.text = settings['llm_api_url'] as String? ?? '';
      _modelController.text = settings['llm_model'] as String? ?? '';
      _imageGenerationEnabled = settings['llm_image_enabled'] as bool? ?? false;
      _imageApiUrlController.text = settings['llm_image_api_url'] as String? ?? '';
      _imageModelController.text = settings['llm_image_model'] as String? ?? '';
      _imageProvider = settings['llm_image_provider'] as String? ?? 'auto';
      _comfyuiApiUrlController.text = settings['llm_comfyui_api_url'] as String? ?? '';
      _comfyuiOutputNodeController.text =
          (settings['llm_comfyui_output_node'] ?? '13').toString();
      _comfyuiNegativePromptController.text =
          settings['llm_comfyui_negative_prompt'] as String? ?? '';
      _comfyuiWidthController.text =
          (settings['llm_comfyui_width'] ?? 1024).toString();
      _comfyuiHeightController.text =
          (settings['llm_comfyui_height'] ?? 1024).toString();
      _comfyuiStepsController.text =
          (settings['llm_comfyui_steps'] ?? 28).toString();
      _comfyuiCfgController.text =
          (settings['llm_comfyui_cfg'] ?? 1.0).toString();
      _comfyuiSamplerController.text =
          settings['llm_comfyui_sampler'] as String? ?? 'euler';
      _comfyuiSchedulerController.text =
          settings['llm_comfyui_scheduler'] as String? ?? 'simple';
      _comfyuiSeedController.text =
          (settings['llm_comfyui_seed'] ?? 42).toString();
      _comfyuiWorkflowController.text =
          settings['llm_comfyui_workflow'] as String? ?? '';
      _publicBaseUrlController.text = settings['app_public_base_url'] as String? ?? '';
      // API key is not returned for security; leave blank unless user types a new one
      _apiKeyController.text = '';
      _contextWindowController.text = (settings['llm_context_window'] ?? 8192)
          .toString();
      _maxIterationsController.text = (settings['llm_max_iterations'] ?? 25)
          .toString();
      _preserveRecentController.text = (settings['llm_preserve_recent'] ?? 10)
          .toString();
      _toolResultMaxCharsController.text =
          (settings['llm_tool_result_max_chars'] ?? 0).toString();
      _compactionThreshold =
          (settings['llm_compaction_threshold'] as num?)?.toDouble() ?? 0.75;
      final discord = settings['discord'] as Map<String, dynamic>? ?? {};
      _discordEnabled = discord['enabled'] as bool? ?? false;
      _discordTokenController.text = '';
      _discordGuildController.text = discord['guild_id'] as String? ?? '';
      _discordChannelController.text = discord['channel_id'] as String? ?? '';
      _discordPollController.text = (discord['poll_interval_seconds'] ?? 10)
          .toString();
      await _loadDiscordServers();
    } catch (_) {
      _apiUrlController.text = '';
      _modelController.text = 'llama3.1';
      _imageGenerationEnabled = false;
      _imageApiUrlController.text = '';
      _imageModelController.text = '';
      _imageProvider = 'auto';
      _comfyuiApiUrlController.text = '';
      _comfyuiOutputNodeController.text = '13';
      _comfyuiNegativePromptController.text = '';
      _comfyuiWidthController.text = '1024';
      _comfyuiHeightController.text = '1024';
      _comfyuiStepsController.text = '28';
      _comfyuiCfgController.text = '1.0';
      _comfyuiSamplerController.text = 'euler';
      _comfyuiSchedulerController.text = 'simple';
      _comfyuiSeedController.text = '42';
      _comfyuiWorkflowController.text = '';
      _publicBaseUrlController.text = '';
      _contextWindowController.text = '8192';
      _maxIterationsController.text = '25';
      _preserveRecentController.text = '10';
      _toolResultMaxCharsController.text = '0';
      _discordTokenController.text = '';
      _discordGuildController.text = '';
      _discordChannelController.text = '';
      _discordPollController.text = '10';
    }

    if (mounted) setState(() => _isLoading = false);
  }

  Future<void> _loadDiscordServers() async {
    setState(() => _isLoadingDiscordServers = true);
    try {
      final servers = await _api.getDiscordServers();
      if (mounted) {
        setState(() {
          _discordServers = servers;
          _isLoadingDiscordServers = false;
        });
      }
    } catch (_) {
      if (mounted) {
        setState(() => _isLoadingDiscordServers = false);
      }
    }
  }

  Future<void> _saveSettings() async {
    setState(() => _isSaving = true);
    try {
      final contextWindow = int.tryParse(_contextWindowController.text) ?? 8192;
      final maxIterations = int.tryParse(_maxIterationsController.text) ?? 25;
      final preserveRecent = int.tryParse(_preserveRecentController.text) ?? 10;
      final toolResultMaxChars =
          int.tryParse(_toolResultMaxCharsController.text) ?? 0;
      final discordPoll = int.tryParse(_discordPollController.text) ?? 10;

      // Build the settings payload — only include API key if user entered one
      final payload = <String, dynamic>{
        'llm_api_url': _apiUrlController.text,
        'llm_model': _modelController.text,
        'llm_image_enabled': _imageGenerationEnabled,
        'llm_image_api_url': _imageApiUrlController.text,
        'llm_image_model': _imageModelController.text,
        'llm_image_provider': _imageProvider,
        'llm_comfyui_api_url': _comfyuiApiUrlController.text,
        'llm_comfyui_output_node': _comfyuiOutputNodeController.text,
        'llm_comfyui_negative_prompt': _comfyuiNegativePromptController.text,
        'llm_comfyui_width': int.tryParse(_comfyuiWidthController.text) ?? 1024,
        'llm_comfyui_height': int.tryParse(_comfyuiHeightController.text) ?? 1024,
        'llm_comfyui_steps': int.tryParse(_comfyuiStepsController.text) ?? 28,
        'llm_comfyui_cfg':
            double.tryParse(_comfyuiCfgController.text) ?? 1.0,
        'llm_comfyui_sampler': _comfyuiSamplerController.text,
        'llm_comfyui_scheduler': _comfyuiSchedulerController.text,
        'llm_comfyui_seed': int.tryParse(_comfyuiSeedController.text) ?? 42,
        'llm_comfyui_workflow': _comfyuiWorkflowController.text,
        'app_public_base_url': _publicBaseUrlController.text,
        'llm_max_iterations': maxIterations,
        'llm_context_window': contextWindow,
        'llm_compaction_threshold': _compactionThreshold,
        'llm_preserve_recent': preserveRecent,
        'llm_tool_result_max_chars': toolResultMaxChars,
        'discord_enabled': _discordEnabled,
        'discord_poll_interval_seconds': discordPoll,
      };
      if (_discordGuildController.text.isNotEmpty) {
        payload['discord_guild_id'] = _discordGuildController.text;
      }
      if (_discordChannelController.text.isNotEmpty) {
        payload['discord_channel_id'] = _discordChannelController.text;
      }
      if (_apiKeyController.text.isNotEmpty) {
        payload['llm_api_key'] = _apiKeyController.text;
      }
      if (_discordTokenController.text.isNotEmpty) {
        payload['discord_bot_token'] = _discordTokenController.text;
      }

      await _api.saveSettingsToBackend(payload);

      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(
            content: const Text('Settings saved'),
            backgroundColor: const Color(0xFF16161E),
            behavior: SnackBarBehavior.floating,
            shape: RoundedRectangleBorder(
              borderRadius: BorderRadius.circular(10),
            ),
          ),
        );
      }
    } catch (e) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(
            content: Text('Failed to save settings: $e'),
            backgroundColor: Colors.red.shade800,
            behavior: SnackBarBehavior.floating,
            shape: RoundedRectangleBorder(
              borderRadius: BorderRadius.circular(10),
            ),
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
    _imageApiUrlController.dispose();
    _imageModelController.dispose();
    _comfyuiApiUrlController.dispose();
    _comfyuiOutputNodeController.dispose();
    _comfyuiNegativePromptController.dispose();
    _comfyuiWidthController.dispose();
    _comfyuiHeightController.dispose();
    _comfyuiStepsController.dispose();
    _comfyuiCfgController.dispose();
    _comfyuiSamplerController.dispose();
    _comfyuiSchedulerController.dispose();
    _comfyuiSeedController.dispose();
    _comfyuiWorkflowController.dispose();
    _publicBaseUrlController.dispose();
    _maxIterationsController.dispose();
    _contextWindowController.dispose();
    _preserveRecentController.dispose();
    _toolResultMaxCharsController.dispose();
    _discordTokenController.dispose();
    _discordGuildController.dispose();
    _discordChannelController.dispose();
    _discordPollController.dispose();
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
                shape: RoundedRectangleBorder(
                  borderRadius: BorderRadius.circular(10),
                ),
              ),
              child: _isSaving
                  ? const SizedBox(
                      width: 16,
                      height: 16,
                      child: CircularProgressIndicator(
                        strokeWidth: 2,
                        color: Colors.white,
                      ),
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
          : DefaultTabController(
              length: 4,
              child: Column(
                children: [
                  Container(
                    color: const Color(0xFF0D0D12),
                    padding: const EdgeInsets.symmetric(horizontal: 24),
                    child: const TabBar(
                      indicatorColor: Color(0xFF8B5CF6),
                      labelColor: Colors.white,
                      unselectedLabelColor: Color(0xFF71717A),
                      isScrollable: true,
                      tabs: [
                        Tab(text: 'About'),
                        Tab(text: 'LLM'),
                        Tab(text: 'Discord'),
                        Tab(text: 'Tools'),
                      ],
                    ),
                  ),
                  Expanded(
                    child: TabBarView(
                      children: [
                        _buildAboutSettingsTab(),
                        _buildLlmSettingsTab(),
                        _buildDiscordSettingsTab(),
                        _buildToolsSettingsTab(),
                      ],
                    ),
                  ),
                ],
              ),
            ),
    );
  }

  Widget _buildSettingsTab(List<Widget> children, {double maxWidth = 600}) {
    return SingleChildScrollView(
      padding: const EdgeInsets.all(24),
      child: Center(
        child: ConstrainedBox(
          constraints: BoxConstraints(maxWidth: maxWidth),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: children,
          ),
        ),
      ),
    );
  }

  Widget _buildAboutSettingsTab() {
    return _buildSettingsTab([
      _buildSection('About', 'ThreadBot v1.0', Icons.info_outline_rounded, [
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
                  const ThreadbotAvatar(
                    size: 56,
                    borderRadius: 14,
                    showNeedle: false,
                    showShadow: false,
                  ),
                  const SizedBox(width: 12),
                  const Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text(
                        'ThreadBot',
                        style: TextStyle(
                          fontSize: 16,
                          fontWeight: FontWeight.w600,
                        ),
                      ),
                      Text(
                        'Temporal-powered AI chatbot',
                        style: TextStyle(
                          fontSize: 12,
                          color: Color(0xFF71717A),
                        ),
                      ),
                    ],
                  ),
                ],
              ),
              const SizedBox(height: 16),
              const _FeatureRow(
                icon: Icons.chat_bubble_outline,
                text: 'Thread-based conversations',
              ),
              const _FeatureRow(
                icon: Icons.webhook_outlined,
                text: 'Temporal workflow orchestration',
              ),
              const _FeatureRow(
                icon: Icons.api_outlined,
                text: 'OpenAI-compatible API support',
              ),
              const _FeatureRow(
                icon: Icons.layers_outlined,
                text: 'Dockerized MCP tool servers',
              ),
              const _FeatureRow(
                icon: Icons.compress_rounded,
                text: 'Automatic context compaction',
              ),
              const _FeatureRow(
                icon: Icons.cloud_outlined,
                text: 'Docker & Kubernetes ready',
              ),
            ],
          ),
        ),
      ]),
    ]);
  }

  Widget _buildLlmSettingsTab() {
    return _buildSettingsTab([
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
            hint: 'Leave blank to keep current key',
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
        'Image Generation',
        'Use a separate image model/backend for generated images',
        Icons.image_outlined,
        [
          SwitchListTile(
            contentPadding: EdgeInsets.zero,
            value: _imageGenerationEnabled,
            onChanged: (v) => setState(() => _imageGenerationEnabled = v),
            activeThumbColor: const Color(0xFF8B5CF6),
            title: const Text('Enable image generation'),
            subtitle: Text(
              'When enabled, ThreadBot can call the built-in generate_image tool. Image analysis still uses the main multimodal chat model.',
              style: TextStyle(
                fontSize: 12,
                color: Colors.white.withValues(alpha: 0.4),
              ),
            ),
          ),
          const SizedBox(height: 16),
          _buildImageProviderDropdown(),
          _buildField(
            controller: _publicBaseUrlController,
            label: 'Public Base URL',
            hint: 'https://threadbot.example.com (optional)',
            icon: Icons.public_rounded,
          ),
          const SizedBox(height: 12),
          if (_imageProvider == 'comfyui') ...[
            _buildInfoBox(
              'ComfyUI uses the workflow to decide the model/style. The bundled default is Flux.1-dev on ollama.home:8188. Leave Image Model hidden because it is not used for ComfyUI.',
            ),
            const SizedBox(height: 16),
            _buildField(
              controller: _comfyuiApiUrlController,
              label: 'ComfyUI API URL',
              hint: 'http://ollama.home:8188',
              icon: Icons.hub_outlined,
            ),
            const SizedBox(height: 16),
            _buildField(
              controller: _comfyuiOutputNodeController,
              label: 'Save Image Node ID',
              hint: '13',
              icon: Icons.output_rounded,
            ),
            const SizedBox(height: 16),
            _buildField(
              controller: _comfyuiNegativePromptController,
              label: 'Negative Prompt',
              hint: 'Optional; Flux workflows usually leave this blank',
              icon: Icons.block_rounded,
            ),
            const SizedBox(height: 16),
            Row(
              children: [
                Expanded(
                  child: _buildField(
                    controller: _comfyuiWidthController,
                    label: 'Width',
                    hint: '1024',
                    icon: Icons.straighten_rounded,
                    keyboardType: TextInputType.number,
                  ),
                ),
                const SizedBox(width: 12),
                Expanded(
                  child: _buildField(
                    controller: _comfyuiHeightController,
                    label: 'Height',
                    hint: '1024',
                    icon: Icons.straighten_rounded,
                    keyboardType: TextInputType.number,
                  ),
                ),
              ],
            ),
            const SizedBox(height: 16),
            Row(
              children: [
                Expanded(
                  child: _buildField(
                    controller: _comfyuiStepsController,
                    label: 'Steps',
                    hint: '28',
                    icon: Icons.repeat_rounded,
                    keyboardType: TextInputType.number,
                  ),
                ),
                const SizedBox(width: 12),
                Expanded(
                  child: _buildField(
                    controller: _comfyuiCfgController,
                    label: 'CFG',
                    hint: '1.0',
                    icon: Icons.tune_rounded,
                    keyboardType: TextInputType.number,
                  ),
                ),
                const SizedBox(width: 12),
                Expanded(
                  child: _buildField(
                    controller: _comfyuiSeedController,
                    label: 'Seed',
                    hint: '42',
                    icon: Icons.casino_outlined,
                    keyboardType: TextInputType.number,
                  ),
                ),
              ],
            ),
            const SizedBox(height: 16),
            Row(
              children: [
                Expanded(
                  child: _buildField(
                    controller: _comfyuiSamplerController,
                    label: 'Sampler',
                    hint: 'euler',
                    icon: Icons.gradient_rounded,
                  ),
                ),
                const SizedBox(width: 12),
                Expanded(
                  child: _buildField(
                    controller: _comfyuiSchedulerController,
                    label: 'Scheduler',
                    hint: 'simple',
                    icon: Icons.schedule_rounded,
                  ),
                ),
              ],
            ),
            const SizedBox(height: 16),
            _buildField(
              controller: _comfyuiWorkflowController,
              label: 'Workflow JSON (optional)',
              hint: 'Leave blank to use bundled Flux.1-dev workflow',
              icon: Icons.data_object_rounded,
              maxLines: 6,
            ),
          ] else ...[
            const SizedBox(height: 16),
            _buildField(
              controller: _imageApiUrlController,
              label: 'Image API URL',
              hint: 'http://ollama.home:11434 or http://host:port/v1',
              icon: Icons.link_rounded,
            ),
            const SizedBox(height: 16),
            _buildField(
              controller: _imageModelController,
              label: 'Image Model',
              hint: 'x/z-image-turbo:fp8',
              icon: Icons.auto_awesome_rounded,
            ),
            const SizedBox(height: 12),
            _buildInfoBox(
              'Ollama image models found on ollama.home include x/z-image-turbo:fp8 and x/flux2-klein:9b. Use provider Ollama for those models. Use OpenAI-compatible only for servers that expose /images/generations.',
            ),
          ],
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
          _buildField(
            controller: _maxIterationsController,
            label: 'Max Conversational Turns',
            hint: '25',
            icon: Icons.repeat_rounded,
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
          _buildInfoBox(
            'When estimated token usage exceeds ${(_compactionThreshold * 100).round()}% of the context window, older messages are summarized automatically.',
          ),
        ],
      ),
    ]);
  }

  Widget _buildToolsSettingsTab() {
    return _buildSettingsTab([
      _buildSection(
        'Tool Calls',
        'Configure MCP tool result handling',
        Icons.build_outlined,
        [
          _buildField(
            controller: _toolResultMaxCharsController,
            label: 'Tool Result Max Characters',
            hint: '0 (no limit)',
            icon: Icons.content_cut_rounded,
            keyboardType: TextInputType.number,
          ),
          const SizedBox(height: 12),
          _buildInfoBox(
            'Truncates large tool results before sending to the LLM. The LLM is told when results are truncated so it can adjust its queries. Set to 0 to disable truncation.',
          ),
        ],
      ),
    ]);
  }

  Widget _buildDiscordSettingsTab() {
    return RefreshIndicator(
      onRefresh: _loadDiscordServers,
      child: _buildSettingsTab([
        _buildSection(
          'Discord Integration',
          'Share selected ThreadBot conversations to Discord threads',
          Icons.forum_outlined,
          [
            SwitchListTile(
              contentPadding: EdgeInsets.zero,
              value: _discordEnabled,
              onChanged: (v) => setState(() => _discordEnabled = v),
              activeThumbColor: const Color(0xFF8B5CF6),
              title: const Text('Enable Discord sync'),
              subtitle: Text(
                'Requires a Discord bot token with channel, thread, and message permissions.',
                style: TextStyle(
                  fontSize: 12,
                  color: Colors.white.withValues(alpha: 0.4),
                ),
              ),
            ),
            const SizedBox(height: 16),
            _buildField(
              controller: _discordTokenController,
              label: 'Discord Bot Token',
              hint: 'Leave blank to keep current token',
              icon: Icons.key_rounded,
              obscure: true,
            ),
            const SizedBox(height: 16),
            _buildField(
              controller: _discordGuildController,
              label: 'Default Server ID',
              hint: 'Discord guild/server ID',
              icon: Icons.groups_outlined,
            ),
            const SizedBox(height: 16),
            _buildField(
              controller: _discordChannelController,
              label: 'Default Channel ID',
              hint: 'Channel where ThreadBot creates Discord threads',
              icon: Icons.tag_rounded,
            ),
            const SizedBox(height: 16),
            _buildField(
              controller: _discordPollController,
              label: 'Reply Poll Interval (seconds)',
              hint: '10',
              icon: Icons.sync_rounded,
              keyboardType: TextInputType.number,
            ),
          ],
        ),
        const SizedBox(height: 32),
        _buildDiscordServersPanel(),
      ], maxWidth: 760),
    );
  }

  Widget _buildInfoBox(String text) {
    return Container(
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
          const Icon(
            Icons.info_outline_rounded,
            size: 16,
            color: Color(0xFF8B5CF6),
          ),
          const SizedBox(width: 8),
          Expanded(
            child: Text(
              text,
              style: TextStyle(
                fontSize: 12,
                color: Colors.white.withValues(alpha: 0.5),
              ),
            ),
          ),
        ],
      ),
    );
  }


  Widget _buildImageProviderDropdown() {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        const Text(
          'Image Provider',
          style: TextStyle(fontSize: 13, fontWeight: FontWeight.w500),
        ),
        const SizedBox(height: 8),
        Container(
          decoration: BoxDecoration(
            borderRadius: BorderRadius.circular(12),
            color: Colors.white.withValues(alpha: 0.03),
            border: Border.all(color: Colors.white.withValues(alpha: 0.08)),
          ),
          child: DropdownButtonFormField<String>(
            initialValue: _imageProvider,
            decoration: const InputDecoration(
              prefixIcon: Icon(Icons.hub_outlined, color: Color(0xFF71717A)),
              border: InputBorder.none,
              contentPadding: EdgeInsets.symmetric(horizontal: 16, vertical: 14),
            ),
            dropdownColor: const Color(0xFF16161E),
            style: const TextStyle(color: Color(0xFFE4E4E7), fontSize: 14),
            items: const [
              DropdownMenuItem(value: 'auto', child: Text('Auto')),
              DropdownMenuItem(value: 'ollama', child: Text('Ollama')),
              DropdownMenuItem(value: 'openai_compatible', child: Text('OpenAI-compatible')),
              DropdownMenuItem(value: 'comfyui', child: Text('ComfyUI')),
            ],
            onChanged: (value) {
              if (value != null) setState(() => _imageProvider = value);
            },
          ),
        ),
      ],
    );
  }

  Widget _buildDiscordServersPanel() {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Row(
          children: [
            const Icon(Icons.discord, color: Color(0xFF8B5CF6)),
            const SizedBox(width: 8),
            const Text(
              'Discord Servers',
              style: TextStyle(fontSize: 16, fontWeight: FontWeight.w600),
            ),
            const Spacer(),
            Text(
              'Connected servers and MCP defaults',
              style: TextStyle(
                fontSize: 12,
                color: Colors.white.withValues(alpha: 0.4),
              ),
            ),
          ],
        ),
        const SizedBox(height: 16),
        if (_isLoadingDiscordServers)
          const Center(
            child: Padding(
              padding: EdgeInsets.all(40),
              child: CircularProgressIndicator(
                valueColor: AlwaysStoppedAnimation(Color(0xFF8B5CF6)),
              ),
            ),
          )
        else if (_discordServers.isEmpty)
          Container(
            width: double.infinity,
            padding: const EdgeInsets.all(20),
            decoration: BoxDecoration(
              borderRadius: BorderRadius.circular(16),
              color: Colors.white.withValues(alpha: 0.03),
              border: Border.all(color: Colors.white.withValues(alpha: 0.06)),
            ),
            child: Text(
              'No Discord servers are connected yet. Create or tag ThreadBot in Discord to register a server here.',
              style: TextStyle(
                fontSize: 13,
                color: Colors.white.withValues(alpha: 0.45),
              ),
            ),
          )
        else
          ..._discordServers.map((server) => _buildDiscordServerRow(server)),
      ],
    );
  }

  Widget _buildDiscordServerRow(Map<String, dynamic> server) {
    final guildName =
        server['guild_name'] as String? ??
        server['guild_id'] as String? ??
        'Discord Server';
    final guildId = server['guild_id'] as String? ?? '';
    final threadCount = server['thread_count'] as int? ?? 0;
    final defaultChannelId = server['default_channel_id'] as String? ?? '';
    return Padding(
      padding: const EdgeInsets.only(bottom: 12),
      child: InkWell(
        borderRadius: BorderRadius.circular(16),
        onTap: () => _openDiscordServerOverrides(server),
        child: Container(
          width: double.infinity,
          padding: const EdgeInsets.all(16),
          decoration: BoxDecoration(
            borderRadius: BorderRadius.circular(16),
            color: Colors.white.withValues(alpha: 0.03),
            border: Border.all(color: Colors.white.withValues(alpha: 0.06)),
          ),
          child: Row(
            children: [
              Container(
                width: 40,
                height: 40,
                alignment: Alignment.center,
                decoration: BoxDecoration(
                  borderRadius: BorderRadius.circular(12),
                  color: const Color(0xFF5865F2).withValues(alpha: 0.15),
                ),
                child: const Icon(Icons.discord, color: Color(0xFF5865F2)),
              ),
              const SizedBox(width: 12),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      guildName,
                      style: const TextStyle(
                        fontSize: 14,
                        fontWeight: FontWeight.w600,
                      ),
                    ),
                    const SizedBox(height: 4),
                    Text(
                      guildId,
                      style: TextStyle(
                        fontSize: 12,
                        color: Colors.white.withValues(alpha: 0.45),
                      ),
                    ),
                    if (defaultChannelId.isNotEmpty) ...[
                      const SizedBox(height: 4),
                      Text(
                        'Default channel: $defaultChannelId',
                        style: TextStyle(
                          fontSize: 12,
                          color: Colors.white.withValues(alpha: 0.45),
                        ),
                      ),
                    ],
                  ],
                ),
              ),
              Column(
                crossAxisAlignment: CrossAxisAlignment.end,
                children: [
                  Text(
                    '$threadCount thread${threadCount == 1 ? '' : 's'}',
                    style: TextStyle(
                      fontSize: 12,
                      color: Colors.white.withValues(alpha: 0.45),
                    ),
                  ),
                  const SizedBox(height: 4),
                  Icon(
                    Icons.chevron_right_rounded,
                    color: Colors.white.withValues(alpha: 0.35),
                  ),
                ],
              ),
            ],
          ),
        ),
      ),
    );
  }

  // ignore: unused_element
  Widget _buildGeneralSettingsTab() {
    return SingleChildScrollView(
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
                    hint: 'Leave blank to keep current key',
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
                  _buildField(
                    controller: _maxIterationsController,
                    label: 'Max Conversational Turns',
                    hint: '25',
                    icon: Icons.repeat_rounded,
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
                        const Icon(
                          Icons.info_outline_rounded,
                          size: 16,
                          color: Color(0xFF8B5CF6),
                        ),
                        const SizedBox(width: 8),
                        Expanded(
                          child: Text(
                            'When estimated token usage exceeds ${(_compactionThreshold * 100).round()}% of the context window, older messages are summarized automatically.',
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
                'Tool Calls',
                'Configure MCP tool result handling',
                Icons.build_outlined,
                [
                  _buildField(
                    controller: _toolResultMaxCharsController,
                    label: 'Tool Result Max Characters',
                    hint: '0 (no limit)',
                    icon: Icons.content_cut_rounded,
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
                        const Icon(
                          Icons.info_outline_rounded,
                          size: 16,
                          color: Color(0xFF8B5CF6),
                        ),
                        const SizedBox(width: 8),
                        Expanded(
                          child: Text(
                            'Truncates large tool results before sending to the LLM. The LLM is told when results are truncated so it can adjust its queries. Set to 0 to disable truncation.',
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
                'Discord Integration',
                'Share selected ThreadBot conversations to Discord threads',
                Icons.forum_outlined,
                [
                  SwitchListTile(
                    contentPadding: EdgeInsets.zero,
                    value: _discordEnabled,
                    onChanged: (v) => setState(() => _discordEnabled = v),
                    activeThumbColor: const Color(0xFF8B5CF6),
                    title: const Text('Enable Discord sync'),
                    subtitle: Text(
                      'Requires a Discord bot token with channel, thread, and message permissions.',
                      style: TextStyle(
                        fontSize: 12,
                        color: Colors.white.withValues(alpha: 0.4),
                      ),
                    ),
                  ),
                  const SizedBox(height: 16),
                  _buildField(
                    controller: _discordTokenController,
                    label: 'Discord Bot Token',
                    hint: 'Leave blank to keep current token',
                    icon: Icons.key_rounded,
                    obscure: true,
                  ),
                  const SizedBox(height: 16),
                  _buildField(
                    controller: _discordGuildController,
                    label: 'Default Server ID',
                    hint: 'Discord guild/server ID',
                    icon: Icons.groups_outlined,
                  ),
                  const SizedBox(height: 16),
                  _buildField(
                    controller: _discordChannelController,
                    label: 'Default Channel ID',
                    hint: 'Channel where ThreadBot creates Discord threads',
                    icon: Icons.tag_rounded,
                  ),
                  const SizedBox(height: 16),
                  _buildField(
                    controller: _discordPollController,
                    label: 'Reply Poll Interval (seconds)',
                    hint: '10',
                    icon: Icons.sync_rounded,
                    keyboardType: TextInputType.number,
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
                      border: Border.all(
                        color: Colors.white.withValues(alpha: 0.06),
                      ),
                    ),
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Row(
                          children: [
                            const ThreadbotAvatar(
                              size: 56,
                              borderRadius: 14,
                              showNeedle: false,
                              showShadow: false,
                            ),
                            const SizedBox(width: 12),
                            const Column(
                              crossAxisAlignment: CrossAxisAlignment.start,
                              children: [
                                Text(
                                  'ThreadBot',
                                  style: TextStyle(
                                    fontSize: 16,
                                    fontWeight: FontWeight.w600,
                                  ),
                                ),
                                Text(
                                  'Temporal-powered AI chatbot',
                                  style: TextStyle(
                                    fontSize: 12,
                                    color: Color(0xFF71717A),
                                  ),
                                ),
                              ],
                            ),
                          ],
                        ),
                        const SizedBox(height: 16),
                        const _FeatureRow(
                          icon: Icons.chat_bubble_outline,
                          text: 'Thread-based conversations',
                        ),
                        const _FeatureRow(
                          icon: Icons.webhook_outlined,
                          text: 'Temporal workflow orchestration',
                        ),
                        const _FeatureRow(
                          icon: Icons.api_outlined,
                          text: 'OpenAI-compatible API support',
                        ),
                        const _FeatureRow(
                          icon: Icons.layers_outlined,
                          text: 'Dockerized MCP tool servers',
                        ),
                        const _FeatureRow(
                          icon: Icons.compress_rounded,
                          text: 'Automatic context compaction',
                        ),
                        const _FeatureRow(
                          icon: Icons.cloud_outlined,
                          text: 'Docker & Kubernetes ready',
                        ),
                      ],
                    ),
                  ),
                ],
              ),
            ],
          ),
        ),
      ),
    );
  }

  // ignore: unused_element
  Widget _buildDiscordServersTab() {
    return RefreshIndicator(
      onRefresh: _loadDiscordServers,
      child: SingleChildScrollView(
        physics: const AlwaysScrollableScrollPhysics(),
        padding: const EdgeInsets.all(24),
        child: Center(
          child: ConstrainedBox(
            constraints: const BoxConstraints(maxWidth: 760),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Row(
                  children: [
                    const Icon(Icons.discord, color: Color(0xFF8B5CF6)),
                    const SizedBox(width: 8),
                    const Text(
                      'Discord Servers',
                      style: TextStyle(
                        fontSize: 16,
                        fontWeight: FontWeight.w600,
                      ),
                    ),
                    const Spacer(),
                    Text(
                      'Connected servers and MCP defaults',
                      style: TextStyle(
                        fontSize: 12,
                        color: Colors.white.withValues(alpha: 0.4),
                      ),
                    ),
                  ],
                ),
                const SizedBox(height: 16),
                if (_isLoadingDiscordServers)
                  const Center(
                    child: Padding(
                      padding: EdgeInsets.all(40),
                      child: CircularProgressIndicator(
                        valueColor: AlwaysStoppedAnimation(Color(0xFF8B5CF6)),
                      ),
                    ),
                  )
                else if (_discordServers.isEmpty)
                  Container(
                    width: double.infinity,
                    padding: const EdgeInsets.all(20),
                    decoration: BoxDecoration(
                      borderRadius: BorderRadius.circular(16),
                      color: Colors.white.withValues(alpha: 0.03),
                      border: Border.all(
                        color: Colors.white.withValues(alpha: 0.06),
                      ),
                    ),
                    child: Text(
                      'No Discord servers are connected yet. Create or tag ThreadBot in Discord to register a server here.',
                      style: TextStyle(
                        fontSize: 13,
                        color: Colors.white.withValues(alpha: 0.45),
                      ),
                    ),
                  )
                else
                  ..._discordServers.map((server) {
                    final guildName =
                        server['guild_name'] as String? ??
                        server['guild_id'] as String? ??
                        'Discord Server';
                    final guildId = server['guild_id'] as String? ?? '';
                    final threadCount = server['thread_count'] as int? ?? 0;
                    final defaultChannelId =
                        server['default_channel_id'] as String? ?? '';
                    return Padding(
                      padding: const EdgeInsets.only(bottom: 12),
                      child: InkWell(
                        borderRadius: BorderRadius.circular(16),
                        onTap: () => _openDiscordServerOverrides(server),
                        child: Container(
                          width: double.infinity,
                          padding: const EdgeInsets.all(16),
                          decoration: BoxDecoration(
                            borderRadius: BorderRadius.circular(16),
                            color: Colors.white.withValues(alpha: 0.03),
                            border: Border.all(
                              color: Colors.white.withValues(alpha: 0.06),
                            ),
                          ),
                          child: Row(
                            children: [
                              Container(
                                width: 40,
                                height: 40,
                                alignment: Alignment.center,
                                decoration: BoxDecoration(
                                  borderRadius: BorderRadius.circular(12),
                                  color: const Color(
                                    0xFF5865F2,
                                  ).withValues(alpha: 0.15),
                                ),
                                child: const Icon(
                                  Icons.discord,
                                  color: Color(0xFF5865F2),
                                ),
                              ),
                              const SizedBox(width: 12),
                              Expanded(
                                child: Column(
                                  crossAxisAlignment: CrossAxisAlignment.start,
                                  children: [
                                    Text(
                                      guildName,
                                      style: const TextStyle(
                                        fontSize: 14,
                                        fontWeight: FontWeight.w600,
                                      ),
                                    ),
                                    const SizedBox(height: 4),
                                    Text(
                                      guildId,
                                      style: TextStyle(
                                        fontSize: 12,
                                        color: Colors.white.withValues(
                                          alpha: 0.45,
                                        ),
                                      ),
                                    ),
                                    if (defaultChannelId.isNotEmpty) ...[
                                      const SizedBox(height: 4),
                                      Text(
                                        'Default channel: $defaultChannelId',
                                        style: TextStyle(
                                          fontSize: 12,
                                          color: Colors.white.withValues(
                                            alpha: 0.45,
                                          ),
                                        ),
                                      ),
                                    ],
                                  ],
                                ),
                              ),
                              Column(
                                crossAxisAlignment: CrossAxisAlignment.end,
                                children: [
                                  Text(
                                    '$threadCount thread${threadCount == 1 ? '' : 's'}',
                                    style: TextStyle(
                                      fontSize: 12,
                                      color: Colors.white.withValues(
                                        alpha: 0.45,
                                      ),
                                    ),
                                  ),
                                  const SizedBox(height: 4),
                                  Icon(
                                    Icons.chevron_right_rounded,
                                    color: Colors.white.withValues(alpha: 0.35),
                                  ),
                                ],
                              ),
                            ],
                          ),
                        ),
                      ),
                    );
                  }),
              ],
            ),
          ),
        ),
      ),
    );
  }

  Future<void> _openDiscordServerOverrides(Map<String, dynamic> server) async {
    try {
      final guildId = server['guild_id'] as String?;
      if (guildId == null || guildId.isEmpty) return;

      final response = await _api.getDiscordServerMcpOverrides(guildId);
      final guildName =
          response['guild_name'] as String? ??
          server['guild_name'] as String? ??
          guildId;
      final mcpServers = (response['servers'] as List<dynamic>? ?? [])
          .cast<Map<String, dynamic>>();
      final overrides = (response['overrides'] as List<dynamic>? ?? [])
          .cast<Map<String, dynamic>>();
      final serverOverrides = <String, bool>{};
      final toolOverrides = <String, bool>{};
      for (final item in overrides) {
        final serverId = item['server_id'].toString();
        final toolName = item['tool_name'] as String?;
        if (toolName == null) {
          serverOverrides[serverId] = item['enabled'] as bool? ?? false;
        } else {
          toolOverrides['$serverId:$toolName'] =
              item['enabled'] as bool? ?? false;
        }
      }
      final expanded = <String>{};
      final serverState = <String, bool>{};
      final toolState = <String, bool>{};
      for (final item in mcpServers) {
        final id = item['id'].toString();
        final serverEnabled = serverOverrides[id] ?? false;
        serverState[id] = serverEnabled;
        final tools = (item['tools'] as List<dynamic>? ?? []);
        final hasToolOverrides = toolOverrides.keys.any(
          (key) => key.startsWith('$id:'),
        );
        for (final tool in tools) {
          final toolName = (tool as Map<String, dynamic>)['name'].toString();
          toolState['$id:$toolName'] =
              toolOverrides['$id:$toolName'] ??
              (hasToolOverrides ? false : serverEnabled);
        }
      }

      if (!mounted) return;
      final saved = await showDialog<bool>(
        context: context,
        builder: (ctx) {
          return StatefulBuilder(
            builder: (ctx, setDialogState) {
              return AlertDialog(
                backgroundColor: const Color(0xFF1B1B26),
                shape: RoundedRectangleBorder(
                  borderRadius: BorderRadius.circular(16),
                ),
                title: Text(
                  guildName,
                  style: const TextStyle(color: Colors.white),
                ),
                content: SizedBox(
                  width: 680,
                  height: 500,
                  child: mcpServers.isEmpty
                      ? Center(
                          child: Text(
                            'No MCP servers configured yet.',
                            style: TextStyle(
                              color: Colors.white.withValues(alpha: 0.45),
                            ),
                          ),
                        )
                      : ListView.separated(
                          itemCount: mcpServers.length,
                          separatorBuilder: (_, __) =>
                              const SizedBox(height: 8),
                          itemBuilder: (_, index) {
                            final item = mcpServers[index];
                            final id = item['id'].toString();
                            final name = item['name']?.toString() ?? id;
                            final tools =
                                (item['tools'] as List<dynamic>? ?? [])
                                    .cast<Map<String, dynamic>>();
                            final enabled = serverState[id] ?? false;
                            final isExpanded = expanded.contains(id);
                            return Container(
                              decoration: BoxDecoration(
                                borderRadius: BorderRadius.circular(12),
                                color: Colors.white.withValues(alpha: 0.03),
                                border: Border.all(
                                  color: Colors.white.withValues(alpha: 0.06),
                                ),
                              ),
                              child: Column(
                                children: [
                                  Padding(
                                    padding: const EdgeInsets.symmetric(
                                      horizontal: 12,
                                      vertical: 8,
                                    ),
                                    child: Row(
                                      children: [
                                        IconButton(
                                          visualDensity: VisualDensity.compact,
                                          onPressed: tools.isEmpty
                                              ? null
                                              : () {
                                                  setDialogState(() {
                                                    if (isExpanded) {
                                                      expanded.remove(id);
                                                    } else {
                                                      expanded.add(id);
                                                    }
                                                  });
                                                },
                                          icon: Icon(
                                            isExpanded
                                                ? Icons.expand_less
                                                : Icons.expand_more,
                                            color: Colors.white.withValues(
                                              alpha: tools.isEmpty ? 0.2 : 0.55,
                                            ),
                                          ),
                                        ),
                                        Expanded(
                                          child: Column(
                                            crossAxisAlignment:
                                                CrossAxisAlignment.start,
                                            children: [
                                              Text(
                                                name,
                                                style: const TextStyle(
                                                  color: Colors.white,
                                                  fontWeight: FontWeight.w600,
                                                ),
                                              ),
                                              const SizedBox(height: 4),
                                              Text(
                                                '${tools.length} cached tool${tools.length == 1 ? '' : 's'}',
                                                style: TextStyle(
                                                  fontSize: 12,
                                                  color: Colors.white
                                                      .withValues(alpha: 0.4),
                                                ),
                                              ),
                                            ],
                                          ),
                                        ),
                                        Switch(
                                          value: enabled,
                                          onChanged: (value) {
                                            setDialogState(() {
                                              serverState[id] = value;
                                              for (final tool in tools) {
                                                final toolName = tool['name']
                                                    .toString();
                                                toolState['$id:$toolName'] =
                                                    value;
                                              }
                                            });
                                          },
                                          activeThumbColor: const Color(
                                            0xFF8B5CF6,
                                          ),
                                        ),
                                      ],
                                    ),
                                  ),
                                  if (isExpanded && tools.isNotEmpty)
                                    Container(
                                      decoration: BoxDecoration(
                                        border: Border(
                                          top: BorderSide(
                                            color: Colors.white.withValues(
                                              alpha: 0.06,
                                            ),
                                          ),
                                        ),
                                      ),
                                      child: Column(
                                        children: tools.map((tool) {
                                          final toolName = tool['name']
                                              .toString();
                                          final description =
                                              tool['description']?.toString() ??
                                              '';
                                          final key = '$id:$toolName';
                                          final toolEnabled =
                                              toolState[key] ?? false;
                                          return Padding(
                                            padding: const EdgeInsets.only(
                                              left: 48,
                                              right: 12,
                                              top: 6,
                                              bottom: 6,
                                            ),
                                            child: Row(
                                              children: [
                                                Expanded(
                                                  child: Column(
                                                    crossAxisAlignment:
                                                        CrossAxisAlignment
                                                            .start,
                                                    children: [
                                                      Text(
                                                        toolName,
                                                        style: TextStyle(
                                                          fontSize: 13,
                                                          color: enabled
                                                              ? Colors.white
                                                                    .withValues(
                                                                      alpha:
                                                                          0.82,
                                                                    )
                                                              : Colors.white
                                                                    .withValues(
                                                                      alpha:
                                                                          0.35,
                                                                    ),
                                                        ),
                                                      ),
                                                      if (description
                                                          .isNotEmpty)
                                                        Text(
                                                          description,
                                                          maxLines: 1,
                                                          overflow: TextOverflow
                                                              .ellipsis,
                                                          style: TextStyle(
                                                            fontSize: 11,
                                                            color: Colors.white
                                                                .withValues(
                                                                  alpha: 0.35,
                                                                ),
                                                          ),
                                                        ),
                                                    ],
                                                  ),
                                                ),
                                                Switch(
                                                  value: enabled && toolEnabled,
                                                  onChanged: enabled
                                                      ? (
                                                          value,
                                                        ) => setDialogState(
                                                          () => toolState[key] =
                                                              value,
                                                        )
                                                      : null,
                                                  activeThumbColor: const Color(
                                                    0xFF8B5CF6,
                                                  ),
                                                ),
                                              ],
                                            ),
                                          );
                                        }).toList(),
                                      ),
                                    ),
                                ],
                              ),
                            );
                          },
                        ),
                ),
                actions: [
                  TextButton(
                    onPressed: () => Navigator.pop(ctx, false),
                    child: const Text(
                      'Cancel',
                      style: TextStyle(color: Colors.white70),
                    ),
                  ),
                  TextButton(
                    onPressed: () => Navigator.pop(ctx, true),
                    child: const Text(
                      'Save',
                      style: TextStyle(color: Color(0xFF8B5CF6)),
                    ),
                  ),
                ],
              );
            },
          );
        },
      );

      if (saved != true) return;

      await _api.saveDiscordServerMcpOverrides(guildId, [
        for (final entry in serverState.entries)
          {'server_id': entry.key, 'tool_name': null, 'enabled': entry.value},
        for (final entry in toolState.entries)
          {
            'server_id': entry.key.split(':').first,
            'tool_name': entry.key.substring(entry.key.indexOf(':') + 1),
            'enabled': entry.value,
          },
      ]);
      await _loadDiscordServers();
    } catch (e) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(
            content: Text('Failed to update Discord server overrides: $e'),
            backgroundColor: Colors.red.shade800,
            behavior: SnackBarBehavior.floating,
            shape: RoundedRectangleBorder(
              borderRadius: BorderRadius.circular(10),
            ),
          ),
        );
      }
    }
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
            Text(
              '50%',
              style: TextStyle(
                fontSize: 11,
                color: Colors.white.withValues(alpha: 0.3),
              ),
            ),
            Text(
              '95%',
              style: TextStyle(
                fontSize: 11,
                color: Colors.white.withValues(alpha: 0.3),
              ),
            ),
          ],
        ),
      ],
    );
  }

  Widget _buildSection(
    String title,
    String subtitle,
    IconData icon,
    List<Widget> children,
  ) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Row(
          children: [
            Icon(icon, size: 20, color: const Color(0xFF8B5CF6)),
            const SizedBox(width: 8),
            Text(
              title,
              style: const TextStyle(fontSize: 16, fontWeight: FontWeight.w600),
            ),
          ],
        ),
        const SizedBox(height: 4),
        Text(
          subtitle,
          style: TextStyle(
            fontSize: 13,
            color: Colors.white.withValues(alpha: 0.4),
          ),
        ),
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
    int maxLines = 1,
  }) {
    return TextField(
      controller: controller,
      obscureText: obscure,
      keyboardType: keyboardType,
      maxLines: maxLines,
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
          Text(
            text,
            style: const TextStyle(fontSize: 13, color: Color(0xFFA1A1AA)),
          ),
        ],
      ),
    );
  }
}
