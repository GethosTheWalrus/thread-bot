import 'dart:convert';

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
  final _comfyuiWorkflowNameController = TextEditingController();
  final _videoWorkflowController = TextEditingController();
  final _videoOutputNodeController = TextEditingController();
  final _videoInputImageNodeController = TextEditingController();
  final _videoPromptNodeController = TextEditingController();
  final _videoNegativeNodeController = TextEditingController();
  final _videoNegativePromptController = TextEditingController();
  final _videoWidthController = TextEditingController();
  final _videoHeightController = TextEditingController();
  final _videoFramesController = TextEditingController();
  final _videoFpsController = TextEditingController();
  final _videoStepsController = TextEditingController();
  final _videoCfgController = TextEditingController();
  final _videoSamplerController = TextEditingController();
  final _videoSchedulerController = TextEditingController();
  final _videoSeedController = TextEditingController();
  final _videoTimeoutController = TextEditingController();
  final _imageToVideoWorkflowController = TextEditingController();
  final _ttsApiUrlController = TextEditingController();
  final _ttsModelController = TextEditingController();
  final _ttsVoiceController = TextEditingController();
  final _ttsFormatController = TextEditingController();
  final _ttsTimeoutController = TextEditingController();
  final _publicBaseUrlController = TextEditingController();
  final _maxIterationsController = TextEditingController();
  final _contextWindowController = TextEditingController();
  final _preserveRecentController = TextEditingController();
  final _toolResultMaxCharsController = TextEditingController();
  final _visionApiUrlController = TextEditingController();
  final _visionApiKeyController = TextEditingController();
  final _visionModelController = TextEditingController();
  final _visionMaxTokensController = TextEditingController();
  final _visionOcrApiUrlController = TextEditingController();
  final _visionOcrModelController = TextEditingController();
  final _visionDetailApiUrlController = TextEditingController();
  final _visionDetailModelController = TextEditingController();
  final _visionStyleApiUrlController = TextEditingController();
  final _visionStyleModelController = TextEditingController();
  final _discordTokenController = TextEditingController();
  final _discordGuildController = TextEditingController();
  final _discordChannelController = TextEditingController();
  final _discordPollController = TextEditingController();
  double _compactionThreshold = 0.75;
  bool _imageGenerationEnabled = false;
  String _imageProvider = 'auto';
  bool _visionEnabled = false;
  bool _visionRecipeEnabled = true;
  bool _visionPipelineEnabled = false;
  bool _videoGenerationEnabled = true;
  bool _audioGenerationEnabled = true;
  String _ttsProvider = 'openai_compatible';
  String _visionProvider = 'auto';
  String _selectedComfyuiWorkflow = 'Flux.2 Klein 9B';
  bool _showComfyuiWorkflowJson = false;
  bool _showVideoWorkflowJson = false;
  bool _showImageToVideoWorkflowJson = false;
  List<Map<String, dynamic>> _comfyuiWorkflowPresets = [];
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
      _imageApiUrlController.text =
          settings['llm_image_api_url'] as String? ?? '';
      _imageModelController.text = settings['llm_image_model'] as String? ?? '';
      _imageProvider = settings['llm_image_provider'] as String? ?? 'auto';
      _comfyuiApiUrlController.text =
          settings['llm_comfyui_api_url'] as String? ?? 'http://ollama.home:8188';
      _comfyuiOutputNodeController.text =
          (settings['llm_comfyui_output_node'] ?? '12').toString();
      _comfyuiNegativePromptController.text =
          settings['llm_comfyui_negative_prompt'] as String? ?? '';
      _comfyuiWidthController.text = (settings['llm_comfyui_width'] ?? 1024)
          .toString();
      _comfyuiHeightController.text = (settings['llm_comfyui_height'] ?? 1024)
          .toString();
      _comfyuiStepsController.text = (settings['llm_comfyui_steps'] ?? 28)
          .toString();
      _comfyuiCfgController.text = (settings['llm_comfyui_cfg'] ?? 1.0)
          .toString();
      _comfyuiSamplerController.text =
          settings['llm_comfyui_sampler'] as String? ?? 'euler';
      _comfyuiSchedulerController.text =
          settings['llm_comfyui_scheduler'] as String? ?? 'simple';
      _comfyuiSeedController.text = (settings['llm_comfyui_seed'] ?? 42)
          .toString();
      _comfyuiWorkflowController.text =
          settings['llm_comfyui_workflow'] as String? ?? '';
      _comfyuiWorkflowPresets = _normalizeComfyuiWorkflowPresets(
        settings['llm_comfyui_workflow_presets'],
      );
      _selectedComfyuiWorkflow =
          settings['llm_comfyui_selected_workflow'] as String? ??
          (_comfyuiWorkflowPresets.isNotEmpty
              ? _comfyuiWorkflowPresets.first['name'].toString()
              : 'Flux.2 Klein 9B');
      _selectComfyuiWorkflow(_selectedComfyuiWorkflow, updateState: false);
      _videoGenerationEnabled = settings['llm_video_enabled'] as bool? ?? true;
      _videoWorkflowController.text =
          settings['llm_comfyui_video_workflow'] as String? ?? '';
      _imageToVideoWorkflowController.text =
          settings['llm_comfyui_image_to_video_workflow'] as String? ?? '';
      _videoOutputNodeController.text =
          settings['llm_comfyui_video_output_node'] as String? ?? '';
      _videoInputImageNodeController.text =
          settings['llm_comfyui_video_input_image_node'] as String? ?? '';
      _videoPromptNodeController.text =
          settings['llm_comfyui_video_prompt_node'] as String? ?? '';
      _videoNegativeNodeController.text =
          settings['llm_comfyui_video_negative_node'] as String? ?? '';
      _videoNegativePromptController.text =
          settings['llm_comfyui_video_negative_prompt'] as String? ??
          'low quality, blurry, distorted, watermark, text artifacts';
      _videoWidthController.text =
          (settings['llm_comfyui_video_width'] ?? 832).toString();
      _videoHeightController.text =
          (settings['llm_comfyui_video_height'] ?? 480).toString();
      _videoFramesController.text =
          (settings['llm_comfyui_video_frames'] ?? 81).toString();
      _videoFpsController.text =
          (settings['llm_comfyui_video_fps'] ?? 16).toString();
      _videoStepsController.text =
          (settings['llm_comfyui_video_steps'] ?? 24).toString();
      _videoCfgController.text =
          (settings['llm_comfyui_video_cfg'] ?? 4.0).toString();
      _videoSamplerController.text =
          settings['llm_comfyui_video_sampler'] as String? ?? 'euler';
      _videoSchedulerController.text =
          settings['llm_comfyui_video_scheduler'] as String? ?? 'simple';
      _videoSeedController.text =
          (settings['llm_comfyui_video_seed'] ?? 42).toString();
      _videoTimeoutController.text =
          (settings['llm_comfyui_video_timeout'] ?? 1800).toString();
      _audioGenerationEnabled = settings['llm_audio_enabled'] as bool? ?? true;
      _ttsProvider =
          settings['llm_tts_provider'] as String? ?? 'openai_compatible';
      _ttsApiUrlController.text =
          settings['llm_tts_api_url'] as String? ??
          'http://ollama.home:5002/v1/audio/speech';
      _ttsModelController.text = settings['llm_tts_model'] as String? ?? 'piper';
      _ttsVoiceController.text =
          settings['llm_tts_voice'] as String? ?? 'en_US-lessac-medium';
      _ttsFormatController.text = settings['llm_tts_format'] as String? ?? 'wav';
      _ttsTimeoutController.text =
          (settings['llm_tts_timeout'] ?? 300).toString();
      _publicBaseUrlController.text =
          settings['app_public_base_url'] as String? ?? '';
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
      _visionEnabled = settings['llm_vision_enabled'] as bool? ?? false;
      _visionRecipeEnabled =
          settings['llm_vision_recipe_enabled'] as bool? ?? true;
      _visionPipelineEnabled =
          settings['llm_vision_pipeline_enabled'] as bool? ?? false;
      _visionProvider = settings['llm_vision_provider'] as String? ?? 'auto';
      _visionApiUrlController.text =
          settings['llm_vision_api_url'] as String? ?? '';
      _visionModelController.text =
          settings['llm_vision_model'] as String? ?? '';
      _visionMaxTokensController.text =
          (settings['llm_vision_max_tokens'] ?? 1200).toString();
      _visionApiKeyController.text = '';
      _visionOcrApiUrlController.text =
          settings['llm_vision_ocr_api_url'] as String? ?? '';
      _visionOcrModelController.text =
          settings['llm_vision_ocr_model'] as String? ?? '';
      _visionDetailApiUrlController.text =
          settings['llm_vision_detail_api_url'] as String? ?? '';
      _visionDetailModelController.text =
          settings['llm_vision_detail_model'] as String? ?? '';
      _visionStyleApiUrlController.text =
          settings['llm_vision_style_api_url'] as String? ?? '';
      _visionStyleModelController.text =
          settings['llm_vision_style_model'] as String? ?? '';
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
      _comfyuiApiUrlController.text = 'http://ollama.home:8188';
      _comfyuiOutputNodeController.text = '12';
      _comfyuiNegativePromptController.text = '';
      _comfyuiWidthController.text = '1024';
      _comfyuiHeightController.text = '1024';
      _comfyuiStepsController.text = '28';
      _comfyuiCfgController.text = '1.0';
      _comfyuiSamplerController.text = 'euler';
      _comfyuiSchedulerController.text = 'simple';
      _comfyuiSeedController.text = '42';
      _comfyuiWorkflowController.text = '';
      _comfyuiWorkflowPresets = [];
      _selectedComfyuiWorkflow = 'Flux.2 Klein 9B';
      _comfyuiWorkflowNameController.text = _selectedComfyuiWorkflow;
      _videoGenerationEnabled = true;
      _videoWorkflowController.text = '';
      _imageToVideoWorkflowController.text = '';
      _videoOutputNodeController.text = '';
      _videoInputImageNodeController.text = '';
      _videoPromptNodeController.text = '';
      _videoNegativeNodeController.text = '';
      _videoNegativePromptController.text =
          'low quality, blurry, distorted, watermark, text artifacts';
      _videoWidthController.text = '832';
      _videoHeightController.text = '480';
      _videoFramesController.text = '81';
      _videoFpsController.text = '16';
      _videoStepsController.text = '24';
      _videoCfgController.text = '4.0';
      _videoSamplerController.text = 'euler';
      _videoSchedulerController.text = 'simple';
      _videoSeedController.text = '42';
      _videoTimeoutController.text = '1800';
      _audioGenerationEnabled = true;
      _ttsProvider = 'openai_compatible';
      _ttsApiUrlController.text = 'http://ollama.home:5002/v1/audio/speech';
      _ttsModelController.text = 'piper';
      _ttsVoiceController.text = 'en_US-lessac-medium';
      _ttsFormatController.text = 'wav';
      _ttsTimeoutController.text = '300';
      _publicBaseUrlController.text = '';
      _contextWindowController.text = '8192';
      _maxIterationsController.text = '25';
      _preserveRecentController.text = '10';
      _toolResultMaxCharsController.text = '0';
      _visionEnabled = false;
      _visionRecipeEnabled = true;
      _visionPipelineEnabled = false;
      _visionProvider = 'auto';
      _visionApiUrlController.text = '';
      _visionModelController.text = '';
      _visionMaxTokensController.text = '1200';
      _visionApiKeyController.text = '';
      _visionOcrApiUrlController.text = '';
      _visionOcrModelController.text = '';
      _visionDetailApiUrlController.text = '';
      _visionDetailModelController.text = '';
      _visionStyleApiUrlController.text = '';
      _visionStyleModelController.text = '';
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

  List<Map<String, dynamic>> _normalizeComfyuiWorkflowPresets(dynamic value) {
    final presets = <Map<String, dynamic>>[];
    if (value is List) {
      for (final item in value) {
        if (item is! Map) continue;
        final name = (item['name'] ?? '').toString().trim();
        final workflow = (item['workflow'] ?? '').toString().trim();
        if (name.isEmpty || workflow.isEmpty) continue;
        presets.add({
          'name': name,
          'description': (item['description'] ?? '').toString(),
          'output_node': (item['output_node'] ?? '').toString(),
          'workflow': workflow,
          'builtin': item['builtin'] == true,
        });
      }
    }
    return presets;
  }

  void _selectComfyuiWorkflow(String name, {bool updateState = true}) {
    Map<String, dynamic>? preset;
    for (final item in _comfyuiWorkflowPresets) {
      if (item['name'] == name) {
        preset = item;
        break;
      }
    }
    void apply() {
      _selectedComfyuiWorkflow = name;
      _comfyuiWorkflowNameController.text = name;
      if (preset != null) {
        _comfyuiWorkflowController.text = preset['workflow']?.toString() ?? '';
        final outputNode = preset['output_node']?.toString() ?? '';
        if (outputNode.isNotEmpty) {
          _comfyuiOutputNodeController.text = outputNode;
        }
      }
    }

    if (updateState) {
      setState(apply);
    } else {
      apply();
    }
  }

  void _syncSelectedComfyuiWorkflowFromEditor() {
    final name = _comfyuiWorkflowNameController.text.trim().isEmpty
        ? _selectedComfyuiWorkflow
        : _comfyuiWorkflowNameController.text.trim();
    if (name.isEmpty || _comfyuiWorkflowController.text.trim().isEmpty) return;
    final preset = {
      'name': name,
      'description': _workflowSummaryText(_comfyuiWorkflowController.text),
      'output_node': _comfyuiOutputNodeController.text.trim(),
      'workflow': _comfyuiWorkflowController.text,
      'builtin': false,
    };
    final index = _comfyuiWorkflowPresets.indexWhere(
      (item) => item['name'] == name,
    );
    if (index >= 0) {
      _comfyuiWorkflowPresets[index] = preset;
    } else {
      _comfyuiWorkflowPresets.add(preset);
    }
    _selectedComfyuiWorkflow = name;
  }

  void _saveComfyuiWorkflowPreset() {
    try {
      jsonDecode(_comfyuiWorkflowController.text);
    } catch (e) {
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(
          content: Text('Workflow JSON is invalid: $e'),
          backgroundColor: Colors.red.shade800,
          behavior: SnackBarBehavior.floating,
        ),
      );
      return;
    }
    setState(_syncSelectedComfyuiWorkflowFromEditor);
  }

  String _workflowSummaryText(String workflowJson) {
    try {
      final decoded = jsonDecode(workflowJson);
      if (decoded is! Map) return 'Invalid workflow shape';
      final counts = <String, int>{};
      final models = <String>{};
      for (final node in decoded.values) {
        if (node is! Map) continue;
        final type = (node['class_type'] ?? 'Unknown').toString();
        counts[type] = (counts[type] ?? 0) + 1;
        final inputs = node['inputs'];
        if (inputs is Map) {
          for (final key in [
            'unet_name',
            'ckpt_name',
            'clip_name',
            'clip_name1',
            'clip_name2',
            'vae_name',
          ]) {
            final value = inputs[key];
            if (value is String && value.isNotEmpty) models.add(value);
          }
        }
      }
      final important = counts.entries
          .where(
            (entry) =>
                entry.key.contains('Loader') ||
                entry.key.contains('Sampler') ||
                entry.key.contains('Scheduler') ||
                entry.key == 'SaveImage',
          )
          .map((entry) => '${entry.key} x${entry.value}')
          .join(', ');
      final modelText = models.isEmpty
          ? 'No explicit model files'
          : models.join(', ');
      return '${decoded.length} nodes. Models: $modelText. Key nodes: ${important.isEmpty ? 'none' : important}.';
    } catch (e) {
      return 'Invalid JSON: $e';
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
      _syncSelectedComfyuiWorkflowFromEditor();

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
        'llm_comfyui_height':
            int.tryParse(_comfyuiHeightController.text) ?? 1024,
        'llm_comfyui_steps': int.tryParse(_comfyuiStepsController.text) ?? 28,
        'llm_comfyui_cfg': double.tryParse(_comfyuiCfgController.text) ?? 1.0,
        'llm_comfyui_sampler': _comfyuiSamplerController.text,
        'llm_comfyui_scheduler': _comfyuiSchedulerController.text,
        'llm_comfyui_seed': int.tryParse(_comfyuiSeedController.text) ?? 42,
        'llm_comfyui_workflow': _comfyuiWorkflowController.text,
        'llm_comfyui_workflow_presets': _comfyuiWorkflowPresets,
        'llm_comfyui_selected_workflow': _selectedComfyuiWorkflow,
        'llm_video_enabled': _videoGenerationEnabled,
        'llm_comfyui_video_workflow': _videoWorkflowController.text,
        'llm_comfyui_image_to_video_workflow':
            _imageToVideoWorkflowController.text,
        'llm_comfyui_video_output_node': _videoOutputNodeController.text,
        'llm_comfyui_video_input_image_node':
            _videoInputImageNodeController.text,
        'llm_comfyui_video_prompt_node': _videoPromptNodeController.text,
        'llm_comfyui_video_negative_node': _videoNegativeNodeController.text,
        'llm_comfyui_video_negative_prompt':
            _videoNegativePromptController.text,
        'llm_comfyui_video_width':
            int.tryParse(_videoWidthController.text) ?? 832,
        'llm_comfyui_video_height':
            int.tryParse(_videoHeightController.text) ?? 480,
        'llm_comfyui_video_frames':
            int.tryParse(_videoFramesController.text) ?? 81,
        'llm_comfyui_video_fps': int.tryParse(_videoFpsController.text) ?? 16,
        'llm_comfyui_video_steps':
            int.tryParse(_videoStepsController.text) ?? 24,
        'llm_comfyui_video_cfg':
            double.tryParse(_videoCfgController.text) ?? 4.0,
        'llm_comfyui_video_sampler': _videoSamplerController.text,
        'llm_comfyui_video_scheduler': _videoSchedulerController.text,
        'llm_comfyui_video_seed': int.tryParse(_videoSeedController.text) ?? 42,
        'llm_comfyui_video_timeout':
            int.tryParse(_videoTimeoutController.text) ?? 1800,
        'llm_audio_enabled': _audioGenerationEnabled,
        'llm_tts_provider': _ttsProvider,
        'llm_tts_api_url': _ttsApiUrlController.text,
        'llm_tts_model': _ttsModelController.text,
        'llm_tts_voice': _ttsVoiceController.text,
        'llm_tts_format': _ttsFormatController.text,
        'llm_tts_timeout': int.tryParse(_ttsTimeoutController.text) ?? 300,
        'app_public_base_url': _publicBaseUrlController.text,
        'llm_max_iterations': maxIterations,
        'llm_context_window': contextWindow,
        'llm_compaction_threshold': _compactionThreshold,
        'llm_preserve_recent': preserveRecent,
        'llm_tool_result_max_chars': toolResultMaxChars,
        'llm_vision_enabled': _visionEnabled,
        'llm_vision_api_url': _visionApiUrlController.text,
        'llm_vision_model': _visionModelController.text,
        'llm_vision_provider': _visionProvider,
        'llm_vision_max_tokens':
            int.tryParse(_visionMaxTokensController.text) ?? 1200,
        'llm_vision_recipe_enabled': _visionRecipeEnabled,
        'llm_vision_pipeline_enabled': _visionPipelineEnabled,
        'llm_vision_ocr_api_url': _visionOcrApiUrlController.text,
        'llm_vision_ocr_model': _visionOcrModelController.text,
        'llm_vision_detail_api_url': _visionDetailApiUrlController.text,
        'llm_vision_detail_model': _visionDetailModelController.text,
        'llm_vision_style_api_url': _visionStyleApiUrlController.text,
        'llm_vision_style_model': _visionStyleModelController.text,
        'discord_enabled': _discordEnabled,
        'discord_poll_interval_seconds': discordPoll,
      };
      if (_visionApiKeyController.text.isNotEmpty) {
        payload['llm_vision_api_key'] = _visionApiKeyController.text;
      }
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
    _comfyuiWorkflowNameController.dispose();
    _videoWorkflowController.dispose();
    _imageToVideoWorkflowController.dispose();
    _videoOutputNodeController.dispose();
    _videoInputImageNodeController.dispose();
    _videoPromptNodeController.dispose();
    _videoNegativeNodeController.dispose();
    _videoNegativePromptController.dispose();
    _videoWidthController.dispose();
    _videoHeightController.dispose();
    _videoFramesController.dispose();
    _videoFpsController.dispose();
    _videoStepsController.dispose();
    _videoCfgController.dispose();
    _videoSamplerController.dispose();
    _videoSchedulerController.dispose();
    _videoSeedController.dispose();
    _videoTimeoutController.dispose();
    _ttsApiUrlController.dispose();
    _ttsModelController.dispose();
    _ttsVoiceController.dispose();
    _ttsFormatController.dispose();
    _ttsTimeoutController.dispose();
    _publicBaseUrlController.dispose();
    _maxIterationsController.dispose();
    _contextWindowController.dispose();
    _preserveRecentController.dispose();
    _toolResultMaxCharsController.dispose();
    _visionApiUrlController.dispose();
    _visionApiKeyController.dispose();
    _visionModelController.dispose();
    _visionMaxTokensController.dispose();
    _visionOcrApiUrlController.dispose();
    _visionOcrModelController.dispose();
    _visionDetailApiUrlController.dispose();
    _visionDetailModelController.dispose();
    _visionStyleApiUrlController.dispose();
    _visionStyleModelController.dispose();
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
              length: 5,
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
                        Tab(text: 'Media'),
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
                        _buildMediaSettingsTab(),
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
        'Chat Model',
        'Configure the main text/reasoning model backend',
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
          _buildInfoBox(
            'When estimated token usage exceeds ${(_compactionThreshold * 100).round()}% of the context window, older messages are summarized automatically.',
          ),
        ],
      ),
    ]);
  }

  Widget _buildMediaSettingsTab() {
    return _buildSettingsTab([
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
          const SizedBox(height: 16),
          _buildField(
            controller: _publicBaseUrlController,
            label: 'Public Base URL',
            hint: 'https://threadbot.example.com (optional)',
            icon: Icons.public_rounded,
          ),
          const SizedBox(height: 12),
          if (_imageProvider == 'comfyui') ...[
            _buildInfoBox(
              'ComfyUI uses the workflow to decide the model/style. The bundled default is Flux.2 Klein 9B on ollama.home:8188. Leave Image Model hidden because it is not used for ComfyUI.',
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
              hint: '12',
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
            _buildComfyuiWorkflowSelector(),
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
        'Video Generation',
        'Use ComfyUI/Wan workflows for text-to-video and image-to-video',
        Icons.movie_creation_outlined,
        [
          SwitchListTile(
            contentPadding: EdgeInsets.zero,
            value: _videoGenerationEnabled,
            onChanged: (v) => setState(() => _videoGenerationEnabled = v),
            activeThumbColor: const Color(0xFF8B5CF6),
            title: const Text('Enable video generation'),
            subtitle: Text(
              'Enables generate_video and image_to_video. Uses the same ComfyUI API URL above, defaulting to your ollama.home:8188 instance.',
              style: TextStyle(
                fontSize: 12,
                color: Colors.white.withValues(alpha: 0.4),
              ),
            ),
          ),
          const SizedBox(height: 12),
          _buildInfoBox(
            'Defaults are conservative for Wan2.2 14B quantized on an RTX 3090: 832x480, 81 frames, 16 fps, 24 steps, CFG 4.0, timeout 1800s. Paste an exported ComfyUI API workflow JSON below; node ID fields can be left blank for heuristic patching.',
          ),
          const SizedBox(height: 16),
          Row(
            children: [
              Expanded(
                child: _buildField(
                  controller: _videoOutputNodeController,
                  label: 'Video Output Node ID',
                  hint: 'optional; SaveVideo/VHS node',
                  icon: Icons.output_rounded,
                ),
              ),
              const SizedBox(width: 12),
              Expanded(
                child: _buildField(
                  controller: _videoInputImageNodeController,
                  label: 'Input Image Node ID',
                  hint: 'optional; LoadImage node for I2V',
                  icon: Icons.add_photo_alternate_outlined,
                ),
              ),
            ],
          ),
          const SizedBox(height: 16),
          Row(
            children: [
              Expanded(
                child: _buildField(
                  controller: _videoPromptNodeController,
                  label: 'Prompt Node ID',
                  hint: 'optional; positive prompt node',
                  icon: Icons.text_fields_rounded,
                ),
              ),
              const SizedBox(width: 12),
              Expanded(
                child: _buildField(
                  controller: _videoNegativeNodeController,
                  label: 'Negative Node ID',
                  hint: 'optional; negative prompt node',
                  icon: Icons.block_rounded,
                ),
              ),
            ],
          ),
          const SizedBox(height: 16),
          _buildField(
            controller: _videoNegativePromptController,
            label: 'Video Negative Prompt',
            hint: 'low quality, blurry, distorted, watermark, text artifacts',
            icon: Icons.block_rounded,
          ),
          const SizedBox(height: 16),
          Row(
            children: [
              Expanded(
                child: _buildField(
                  controller: _videoWidthController,
                  label: 'Width',
                  hint: '832',
                  icon: Icons.straighten_rounded,
                  keyboardType: TextInputType.number,
                ),
              ),
              const SizedBox(width: 12),
              Expanded(
                child: _buildField(
                  controller: _videoHeightController,
                  label: 'Height',
                  hint: '480',
                  icon: Icons.straighten_rounded,
                  keyboardType: TextInputType.number,
                ),
              ),
              const SizedBox(width: 12),
              Expanded(
                child: _buildField(
                  controller: _videoFramesController,
                  label: 'Frames',
                  hint: '81',
                  icon: Icons.video_library_outlined,
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
                  controller: _videoFpsController,
                  label: 'FPS',
                  hint: '16',
                  icon: Icons.speed_rounded,
                  keyboardType: TextInputType.number,
                ),
              ),
              const SizedBox(width: 12),
              Expanded(
                child: _buildField(
                  controller: _videoStepsController,
                  label: 'Steps',
                  hint: '24',
                  icon: Icons.repeat_rounded,
                  keyboardType: TextInputType.number,
                ),
              ),
              const SizedBox(width: 12),
              Expanded(
                child: _buildField(
                  controller: _videoCfgController,
                  label: 'CFG',
                  hint: '4.0',
                  icon: Icons.tune_rounded,
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
                  controller: _videoSamplerController,
                  label: 'Sampler',
                  hint: 'euler',
                  icon: Icons.gradient_rounded,
                ),
              ),
              const SizedBox(width: 12),
              Expanded(
                child: _buildField(
                  controller: _videoSchedulerController,
                  label: 'Scheduler',
                  hint: 'simple',
                  icon: Icons.schedule_rounded,
                ),
              ),
            ],
          ),
          const SizedBox(height: 16),
          Row(
            children: [
              Expanded(
                child: _buildField(
                  controller: _videoSeedController,
                  label: 'Seed',
                  hint: '42',
                  icon: Icons.casino_outlined,
                  keyboardType: TextInputType.number,
                ),
              ),
              const SizedBox(width: 12),
              Expanded(
                child: _buildField(
                  controller: _videoTimeoutController,
                  label: 'Timeout Seconds',
                  hint: '1800',
                  icon: Icons.timer_outlined,
                  keyboardType: TextInputType.number,
                ),
              ),
            ],
          ),
          const SizedBox(height: 16),
          _buildVideoWorkflowCard(
            title: 'Text-to-Video Workflow',
            description:
                'Official Wan2.2 5B text-to-video workflow. This is what generate_video uses.',
            controller: _videoWorkflowController,
            showJson: _showVideoWorkflowJson,
            onShowJsonChanged: (value) =>
                setState(() => _showVideoWorkflowJson = value),
            jsonHint:
                'Paste the official Wan2.2 text-to-video workflow JSON. UI export or API format is accepted.',
            icon: Icons.movie_creation_outlined,
          ),
          const SizedBox(height: 16),
          _buildVideoWorkflowCard(
            title: 'Image-to-Video Workflow',
            description:
                'Official Wan2.2 5B image-to-video workflow. Used when animating uploaded, generated, or reference images.',
            controller: _imageToVideoWorkflowController,
            showJson: _showImageToVideoWorkflowJson,
            onShowJsonChanged: (value) =>
                setState(() => _showImageToVideoWorkflowJson = value),
            jsonHint:
                'Paste the official Wan2.2 image-to-video workflow JSON. Leave blank to reuse text-to-video workflow.',
            icon: Icons.video_camera_back_outlined,
          ),
        ],
      ),
      const SizedBox(height: 32),
      _buildSection(
        'Audio Generation',
        'Generate dialog, narration, ambient beds, and sound effects for video',
        Icons.graphic_eq_rounded,
        [
          SwitchListTile(
            contentPadding: EdgeInsets.zero,
            value: _audioGenerationEnabled,
            onChanged: (v) => setState(() => _audioGenerationEnabled = v),
            activeThumbColor: const Color(0xFF8B5CF6),
            title: const Text('Enable audio generation'),
            subtitle: Text(
              'Enables generate_video_with_audio. Dialog/narration is produced by the configured TTS endpoint; ambient/Foley beds are mixed locally with ffmpeg.',
              style: TextStyle(
                fontSize: 12,
                color: Colors.white.withValues(alpha: 0.4),
              ),
            ),
          ),
          const SizedBox(height: 12),
          _buildInfoBox(
            'Default endpoint is an OpenAI-compatible local TTS service on ollama.home:5002. The worker uses ffmpeg to mix voice, ambient soundscape layers, and final video into one generated-media file.',
          ),
          const SizedBox(height: 16),
          Row(
            children: [
              Expanded(child: _buildTtsProviderDropdown()),
              const SizedBox(width: 12),
              Expanded(
                child: _buildField(
                  controller: _ttsApiUrlController,
                  label: 'TTS API URL',
                  hint: 'http://ollama.home:5002/v1/audio/speech',
                  icon: Icons.link_rounded,
                ),
              ),
            ],
          ),
          const SizedBox(height: 16),
          Row(
            children: [
              Expanded(
                child: _buildField(
                  controller: _ttsModelController,
                  label: 'TTS Model',
                  hint: 'piper',
                  icon: Icons.record_voice_over_outlined,
                ),
              ),
              const SizedBox(width: 12),
              Expanded(
                child: _buildField(
                  controller: _ttsVoiceController,
                  label: 'Voice',
                  hint: 'en_US-lessac-medium',
                  icon: Icons.person_outline_rounded,
                ),
              ),
            ],
          ),
          const SizedBox(height: 16),
          Row(
            children: [
              Expanded(
                child: _buildField(
                  controller: _ttsFormatController,
                  label: 'Audio Format',
                  hint: 'wav',
                  icon: Icons.audio_file_outlined,
                ),
              ),
              const SizedBox(width: 12),
              Expanded(
                child: _buildField(
                  controller: _ttsTimeoutController,
                  label: 'TTS Timeout Seconds',
                  hint: '300',
                  icon: Icons.timer_outlined,
                  keyboardType: TextInputType.number,
                ),
              ),
            ],
          ),
        ],
      ),
      const SizedBox(height: 32),
      _buildSection(
        'Computer Vision',
        'Use a dedicated multimodal LLM for image analysis and recipe extraction',
        Icons.visibility_outlined,
        [
          SwitchListTile(
            value: _visionEnabled,
            onChanged: (v) => setState(() => _visionEnabled = v),
            title: const Text('Enable dedicated vision LLM'),
            subtitle: const Text(
                'Use a separate OpenAI-compatible vision endpoint for describe_image and extract_image_recipe.'),
            contentPadding: EdgeInsets.zero,
          ),
          if (_visionEnabled) ...[
            const SizedBox(height: 8),
            _buildField(
              controller: _visionApiUrlController,
              label: 'Vision API URL',
              hint: 'http://strix.home:8080/v1',
              icon: Icons.link_rounded,
            ),
            const SizedBox(height: 12),
            _buildField(
              controller: _visionApiKeyController,
              label: 'Vision API Key (optional)',
              hint: 'leave blank if not required',
              icon: Icons.vpn_key_outlined,
              obscure: true,
            ),
            const SizedBox(height: 12),
            _buildField(
              controller: _visionModelController,
              label: 'Vision Model',
              hint: 'qwen3.6:35b',
              icon: Icons.psychology_outlined,
            ),
            const SizedBox(height: 12),
            _buildField(
              controller: _visionMaxTokensController,
              label: 'Vision Max Tokens',
              hint: '1200',
              icon: Icons.text_fields_rounded,
              keyboardType: TextInputType.number,
            ),
            const SizedBox(height: 12),
            DropdownButtonFormField<String>(
              initialValue: _visionProvider,
              decoration: const InputDecoration(
                labelText: 'Provider',
                prefixIcon: Icon(Icons.dns_outlined),
              ),
              items: const [
                DropdownMenuItem(value: 'auto', child: Text('Auto (OpenAI-compatible)')),
                DropdownMenuItem(value: 'openai_compatible', child: Text('OpenAI-compatible')),
                DropdownMenuItem(value: 'ollama', child: Text('Ollama')),
              ],
              onChanged: (v) {
                if (v != null) setState(() => _visionProvider = v);
              },
            ),
            const SizedBox(height: 12),
            SwitchListTile(
              value: _visionRecipeEnabled,
              onChanged: (v) => setState(() => _visionRecipeEnabled = v),
              title: const Text('Enable extract_image_recipe tool'),
              subtitle: const Text(
                  'Lets the model extract a structured ComfyUI recipe (positive/negative prompt, regions, palette) for re-rendering.'),
              contentPadding: EdgeInsets.zero,
            ),
            const SizedBox(height: 12),
            SwitchListTile(
              value: _visionPipelineEnabled,
              onChanged: (v) => setState(() => _visionPipelineEnabled = v),
              title: const Text('Enable multi-stage local vision pipeline'),
              subtitle: const Text(
                  'Runs primary analysis, optional OCR/detail/style passes, then synthesizes the result. Stages run sequentially to limit VRAM usage.'),
              contentPadding: EdgeInsets.zero,
            ),
            if (_visionPipelineEnabled) ...[
              const SizedBox(height: 12),
              _buildField(
                controller: _visionOcrApiUrlController,
                label: 'OCR Stage API URL (optional)',
                hint: 'http://ollama.home:11434/v1',
                icon: Icons.text_snippet_outlined,
              ),
              const SizedBox(height: 12),
              _buildField(
                controller: _visionOcrModelController,
                label: 'OCR Stage Model (optional)',
                hint: 'small local vision/OCR model',
                icon: Icons.short_text_rounded,
              ),
              const SizedBox(height: 12),
              _buildField(
                controller: _visionDetailApiUrlController,
                label: 'Detail Stage API URL (optional)',
                hint: 'http://ollama.home:11434/v1',
                icon: Icons.search_rounded,
              ),
              const SizedBox(height: 12),
              _buildField(
                controller: _visionDetailModelController,
                label: 'Detail Stage Model (optional)',
                hint: 'small local multimodal model',
                icon: Icons.center_focus_strong_outlined,
              ),
              const SizedBox(height: 12),
              _buildField(
                controller: _visionStyleApiUrlController,
                label: 'Style Stage API URL (optional)',
                hint: 'http://ollama.home:11434/v1',
                icon: Icons.palette_outlined,
              ),
              const SizedBox(height: 12),
              _buildField(
                controller: _visionStyleModelController,
                label: 'Style Stage Model (optional)',
                hint: 'small local multimodal model',
                icon: Icons.auto_awesome_outlined,
              ),
              const SizedBox(height: 12),
              _buildInfoBox(
                'Leave a helper stage blank to skip it. If only a model is provided, the stage uses the primary vision API URL. The style stage is also used for extract_image_recipe when configured.',
              ),
            ],
            const SizedBox(height: 12),
            _buildInfoBox(
              'Strix.home example: API URL http://strix.home:8080/v1 with model qwen3.6:35b (started via ~/start-llama.sh qwen3.6-35b). The vision endpoint uses the OpenAI /v1/chat/completions schema.',
            ),
          ],
        ],
      ),
    ], maxWidth: 760);
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
              contentPadding: EdgeInsets.symmetric(
                horizontal: 16,
                vertical: 14,
              ),
            ),
            dropdownColor: const Color(0xFF16161E),
            style: const TextStyle(color: Color(0xFFE4E4E7), fontSize: 14),
            items: const [
              DropdownMenuItem(value: 'auto', child: Text('Auto')),
              DropdownMenuItem(value: 'ollama', child: Text('Ollama')),
              DropdownMenuItem(
                value: 'openai_compatible',
                child: Text('OpenAI-compatible'),
              ),
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

  Widget _buildTtsProviderDropdown() {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        const Text(
          'TTS Provider',
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
            initialValue: _ttsProvider,
            decoration: const InputDecoration(
              prefixIcon: Icon(
                Icons.record_voice_over_outlined,
                color: Color(0xFF71717A),
              ),
              border: InputBorder.none,
              contentPadding: EdgeInsets.symmetric(
                horizontal: 16,
                vertical: 14,
              ),
            ),
            dropdownColor: const Color(0xFF16161E),
            style: const TextStyle(color: Color(0xFFE4E4E7), fontSize: 14),
            items: const [
              DropdownMenuItem(
                value: 'openai_compatible',
                child: Text('OpenAI-compatible'),
              ),
              DropdownMenuItem(value: 'piper_http', child: Text('Piper HTTP')),
            ],
            onChanged: (value) {
              if (value != null) setState(() => _ttsProvider = value);
            },
          ),
        ),
      ],
    );
  }

  Widget _buildComfyuiWorkflowSelector() {
    final names = _comfyuiWorkflowPresets
        .map((item) => item['name']?.toString() ?? '')
        .where((name) => name.isNotEmpty)
        .toSet()
        .toList();
    if (names.isEmpty) names.add(_selectedComfyuiWorkflow);
    if (!names.contains(_selectedComfyuiWorkflow)) {
      names.add(_selectedComfyuiWorkflow);
    }

    return Container(
      width: double.infinity,
      padding: const EdgeInsets.all(16),
      decoration: BoxDecoration(
        borderRadius: BorderRadius.circular(16),
        color: Colors.white.withValues(alpha: 0.03),
        border: Border.all(color: Colors.white.withValues(alpha: 0.06)),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          const Text(
            'ComfyUI Workflow',
            style: TextStyle(fontSize: 15, fontWeight: FontWeight.w600),
          ),
          const SizedBox(height: 12),
          DropdownButtonFormField<String>(
            initialValue: _selectedComfyuiWorkflow,
            decoration: const InputDecoration(
              labelText: 'Selected Workflow',
              prefixIcon: Icon(
                Icons.account_tree_outlined,
                color: Color(0xFF71717A),
              ),
              border: OutlineInputBorder(),
              contentPadding: EdgeInsets.symmetric(
                horizontal: 16,
                vertical: 14,
              ),
            ),
            dropdownColor: const Color(0xFF16161E),
            style: const TextStyle(color: Color(0xFFE4E4E7), fontSize: 14),
            items: names
                .map((name) => DropdownMenuItem(value: name, child: Text(name)))
                .toList(),
            onChanged: (value) {
              if (value != null) _selectComfyuiWorkflow(value);
            },
          ),
          const SizedBox(height: 12),
          Container(
            width: double.infinity,
            padding: const EdgeInsets.all(12),
            decoration: BoxDecoration(
              borderRadius: BorderRadius.circular(12),
              color: const Color(0xFF0D0D12),
              border: Border.all(color: Colors.white.withValues(alpha: 0.06)),
            ),
            child: _buildWorkflowReadableSummary(),
          ),
          const SizedBox(height: 12),
          Row(
            children: [
              Expanded(
                child: _buildField(
                  controller: _comfyuiWorkflowNameController,
                  label: 'Workflow Name',
                  hint: 'Flux.2 Klein 9B',
                  icon: Icons.badge_outlined,
                ),
              ),
              const SizedBox(width: 12),
              FilledButton.tonalIcon(
                onPressed: _saveComfyuiWorkflowPreset,
                icon: const Icon(Icons.save_outlined, size: 18),
                label: const Text('Save Workflow'),
              ),
            ],
          ),
          const SizedBox(height: 8),
          SwitchListTile(
            contentPadding: EdgeInsets.zero,
            value: _showComfyuiWorkflowJson,
            onChanged: (value) =>
                setState(() => _showComfyuiWorkflowJson = value),
            activeThumbColor: const Color(0xFF8B5CF6),
            title: const Text('View JSON'),
            subtitle: Text(
              'Enable to edit the raw ComfyUI API workflow for the selected preset.',
              style: TextStyle(
                fontSize: 12,
                color: Colors.white.withValues(alpha: 0.4),
              ),
            ),
          ),
          if (_showComfyuiWorkflowJson) ...[
            const SizedBox(height: 12),
            _buildField(
              controller: _comfyuiWorkflowController,
              label: 'Workflow JSON',
              hint: 'ComfyUI API workflow JSON',
              icon: Icons.data_object_rounded,
              maxLines: 10,
            ),
          ],
        ],
      ),
    );
  }

  Widget _buildVideoWorkflowCard({
    required String title,
    required String description,
    required TextEditingController controller,
    required bool showJson,
    required ValueChanged<bool> onShowJsonChanged,
    required String jsonHint,
    required IconData icon,
  }) {
    return Container(
      width: double.infinity,
      padding: const EdgeInsets.all(16),
      decoration: BoxDecoration(
        borderRadius: BorderRadius.circular(16),
        color: Colors.white.withValues(alpha: 0.03),
        border: Border.all(color: Colors.white.withValues(alpha: 0.06)),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              Icon(icon, color: const Color(0xFF8B5CF6), size: 20),
              const SizedBox(width: 8),
              Text(
                title,
                style: const TextStyle(
                  fontSize: 15,
                  fontWeight: FontWeight.w600,
                ),
              ),
            ],
          ),
          const SizedBox(height: 6),
          Text(
            description,
            style: TextStyle(
              fontSize: 12,
              color: Colors.white.withValues(alpha: 0.45),
            ),
          ),
          const SizedBox(height: 12),
          Container(
            width: double.infinity,
            padding: const EdgeInsets.all(12),
            decoration: BoxDecoration(
              borderRadius: BorderRadius.circular(12),
              color: const Color(0xFF0D0D12),
              border: Border.all(color: Colors.white.withValues(alpha: 0.06)),
            ),
            child: _buildWorkflowReadableSummaryFor(controller.text),
          ),
          const SizedBox(height: 8),
          SwitchListTile(
            contentPadding: EdgeInsets.zero,
            value: showJson,
            onChanged: onShowJsonChanged,
            activeThumbColor: const Color(0xFF8B5CF6),
            title: const Text('View JSON'),
            subtitle: Text(
              'Enable to inspect or replace this raw ComfyUI workflow.',
              style: TextStyle(
                fontSize: 12,
                color: Colors.white.withValues(alpha: 0.4),
              ),
            ),
          ),
          if (showJson) ...[
            const SizedBox(height: 12),
            _buildField(
              controller: controller,
              label: '$title JSON',
              hint: jsonHint,
              icon: Icons.data_object_rounded,
              maxLines: 10,
            ),
          ],
        ],
      ),
    );
  }

  Widget _buildWorkflowReadableSummary() {
    return _buildWorkflowReadableSummaryFor(_comfyuiWorkflowController.text);
  }

  Widget _buildWorkflowReadableSummaryFor(String workflowJson) {
    try {
      if (workflowJson.trim().isEmpty) {
        return const Text('No workflow JSON configured.');
      }
      final decoded = jsonDecode(workflowJson);
      if (decoded is! Map) {
        return const Text('Workflow JSON must be an object.');
      }
      final counts = <String, int>{};
      final models = <String>{};
      final nodes = _workflowNodes(decoded);
      for (final node in nodes) {
        if (node is! Map) continue;
        final type = (node['class_type'] ?? node['type'] ?? 'Unknown').toString();
        counts[type] = (counts[type] ?? 0) + 1;
        final inputs = node['inputs'];
        if (inputs is Map) {
          for (final key in [
            'unet_name',
            'ckpt_name',
            'clip_name',
            'clip_name1',
            'clip_name2',
            'vae_name',
          ]) {
            final value = inputs[key];
            if (value is String && value.isNotEmpty) models.add(value);
          }
        }
        final widgets = node['widgets_values'];
        if (widgets is List) {
          for (final value in widgets) {
            if (value is String && _looksLikeModelFile(value)) {
              models.add(value);
            }
          }
        }
      }
      final keyNodes = counts.entries
          .where(
            (entry) =>
                entry.key.contains('Loader') ||
                entry.key.contains('Sampler') ||
                entry.key.contains('Scheduler') ||
                entry.key == 'SaveImage' ||
                entry.key == 'SaveVideo' ||
                entry.key == 'SaveWEBM' ||
                entry.key.contains('Wan'),
          )
          .map((entry) => '${entry.key} x${entry.value}')
          .toList();
      return Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(
            '${nodes.length} workflow nodes',
            style: const TextStyle(fontSize: 13, fontWeight: FontWeight.w600),
          ),
          const SizedBox(height: 10),
          _buildWorkflowChipGroup('Model files', models.toList()),
          const SizedBox(height: 10),
          _buildWorkflowChipGroup('Key nodes', keyNodes),
        ],
      );
    } catch (e) {
      return Text(
        'Invalid JSON: $e',
        style: TextStyle(fontSize: 12, color: Colors.red.shade300),
      );
    }
  }

  List<dynamic> _workflowNodes(Map<dynamic, dynamic> decoded) {
    final uiNodes = decoded['nodes'];
    if (uiNodes is List) return uiNodes;
    return decoded.values.toList();
  }

  bool _looksLikeModelFile(String value) {
    final lower = value.toLowerCase();
    return lower.endsWith('.safetensors') ||
        lower.endsWith('.ckpt') ||
        lower.endsWith('.pt') ||
        lower.endsWith('.pth') ||
        lower.endsWith('.bin');
  }

  Widget _buildWorkflowChipGroup(String label, List<String> values) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text(
          label,
          style: TextStyle(
            fontSize: 11,
            color: Colors.white.withValues(alpha: 0.42),
          ),
        ),
        const SizedBox(height: 6),
        Wrap(
          spacing: 6,
          runSpacing: 6,
          children: (values.isEmpty ? ['None detected'] : values).map((value) {
            return Container(
              padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 4),
              decoration: BoxDecoration(
                borderRadius: BorderRadius.circular(999),
                color: const Color(0xFF8B5CF6).withValues(alpha: 0.12),
                border: Border.all(
                  color: const Color(0xFF8B5CF6).withValues(alpha: 0.18),
                ),
              ),
              child: Text(
                value,
                style: const TextStyle(fontSize: 11, color: Color(0xFFC4B5FD)),
              ),
            );
          }).toList(),
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
