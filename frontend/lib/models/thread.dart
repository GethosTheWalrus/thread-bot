import 'package:threadbot/models/message.dart';

const threadApprovalPresets = ['all', 'effectful', 'never'];

String _approvalPreset(dynamic value) {
  final preset = value as String?;
  return threadApprovalPresets.contains(preset) ? preset! : 'effectful';
}

int _contextInt(dynamic value, [int fallback = 0]) {
  if (value is int) return value;
  if (value is num) return value.round();
  return int.tryParse('$value') ?? fallback;
}

double _contextDouble(dynamic value, [double fallback = 0]) {
  if (value is num) return value.toDouble();
  return double.tryParse('$value') ?? fallback;
}

class ContextBudget {
  final int contextWindow;
  final int maxOutputTokens;
  final int inputBudget;
  final int estimatedTokens;
  final int remainingTokens;
  final double usageRatio;
  final double compactionThreshold;
  final int compactionAtTokens;
  final int tokensUntilCompaction;
  final String estimator;

  ContextBudget({
    required this.contextWindow,
    required this.maxOutputTokens,
    required this.inputBudget,
    required this.estimatedTokens,
    required this.remainingTokens,
    required this.usageRatio,
    required this.compactionThreshold,
    required this.compactionAtTokens,
    required this.tokensUntilCompaction,
    required this.estimator,
  });

  factory ContextBudget.fromJson(Map<String, dynamic> json) => ContextBudget(
    contextWindow: _contextInt(json['context_window']),
    maxOutputTokens: _contextInt(json['max_output_tokens']),
    inputBudget: _contextInt(json['input_budget']),
    estimatedTokens: _contextInt(json['estimated_tokens']),
    remainingTokens: _contextInt(json['remaining_tokens']),
    usageRatio: _contextDouble(json['usage_ratio']),
    compactionThreshold: _contextDouble(json['compaction_threshold']),
    compactionAtTokens: _contextInt(json['compaction_at_tokens']),
    tokensUntilCompaction: _contextInt(json['tokens_until_compaction']),
    estimator: json['estimator'] as String? ?? 'chars/4',
  );
}

class ContextCompositionItem {
  final String key;
  final String label;
  final int tokens;
  final int messageCount;
  ContextCompositionItem({
    required this.key,
    required this.label,
    required this.tokens,
    required this.messageCount,
  });

  factory ContextCompositionItem.fromJson(Map<String, dynamic> json) =>
      ContextCompositionItem(
        key: json['key'] as String? ?? '',
        label: json['label'] as String? ?? json['key'] as String? ?? '',
        tokens: _contextInt(json['tokens']),
        messageCount: _contextInt(json['message_count']),
      );
}

class ContextSummary {
  final String content;
  final DateTime? updatedAt;
  final int turnCount;
  final int currentTurnCount;
  final bool stale;

  ContextSummary({
    required this.content,
    required this.updatedAt,
    required this.turnCount,
    required this.currentTurnCount,
    required this.stale,
  });

  factory ContextSummary.fromJson(Map<String, dynamic> json) => ContextSummary(
    content: json['content'] as String? ?? '',
    updatedAt: DateTime.tryParse(json['updated_at'] as String? ?? ''),
    turnCount: _contextInt(json['turn_count']),
    currentTurnCount: _contextInt(json['current_turn_count']),
    stale: json['stale'] as bool? ?? false,
  );
}

class ThreadContext {
  final String threadId;
  final ContextBudget budget;
  final List<ContextCompositionItem> composition;
  final ContextSummary? summary;

  ThreadContext({
    required this.threadId,
    required this.budget,
    required this.composition,
    required this.summary,
  });

  factory ThreadContext.fromJson(Map<String, dynamic> json) => ThreadContext(
    threadId: json['thread_id'] as String? ?? '',
    budget: ContextBudget.fromJson(
      json['budget'] as Map<String, dynamic>? ?? const {},
    ),
    composition: (json['composition'] as List<dynamic>? ?? const [])
        .whereType<Map<String, dynamic>>()
        .map(ContextCompositionItem.fromJson)
        .toList(),
    summary: json['summary'] is Map<String, dynamic>
        ? ContextSummary.fromJson(json['summary'] as Map<String, dynamic>)
        : null,
  );
}

class Thread {
  final String id;
  final String title;
  final String? parentId;
  final DateTime createdAt;
  final DateTime updatedAt;
  final List<Message> messages;
  final bool isGenerating;
  final DiscordThreadLink? discordLink;
  final bool reachyConnected;
  final int estimatedTokens;
  final int contextWindow;
  final bool hasLlmOverrides;
  final bool isPinned;
  final String mode;
  final ThreadAgentSummary? agent;
  final ThreadRunSummary? latestActiveRun;
  final List<ThreadAgentSummary> agents;
  final List<ThreadRunSummary> activeRuns;
  final int pendingApprovals;
  final int agentTurnLimit;
  final String approvalPreset;

  Thread({
    required this.id,
    required this.title,
    this.parentId,
    required this.createdAt,
    required this.updatedAt,
    this.messages = const [],
    this.isGenerating = false,
    this.discordLink,
    this.reachyConnected = false,
    this.estimatedTokens = 0,
    this.contextWindow = 8192,
    this.hasLlmOverrides = false,
    this.isPinned = false,
    this.mode = 'chat',
    this.agent,
    this.latestActiveRun,
    this.agents = const [],
    this.activeRuns = const [],
    this.pendingApprovals = 0,
    this.agentTurnLimit = 0,
    this.approvalPreset = 'effectful',
  });

  factory Thread.fromJson(Map<String, dynamic> json) {
    final messagesJson = json['messages'] as List<dynamic>? ?? [];
    final messages = messagesJson
        .map((m) => Message.fromJson(m as Map<String, dynamic>))
        .toList();

    final agents = _threadAgents(json['agents'], json['agent']);
    final activeRuns = _threadRuns(
      json['active_runs'],
      json['latest_active_run'],
    );
    return Thread(
      id: json['id'] as String,
      title: json['title'] as String,
      parentId: json['parent_id'] as String?,
      createdAt: DateTime.parse(json['created_at'] as String),
      updatedAt: DateTime.parse(json['updated_at'] as String),
      messages: messages,
      isGenerating: json['is_generating'] as bool? ?? false,
      discordLink: json['discord_link'] != null
          ? DiscordThreadLink.fromJson(
              json['discord_link'] as Map<String, dynamic>,
            )
          : null,
      reachyConnected: json['reachy_connected'] as bool? ?? false,
      estimatedTokens: json['estimated_tokens'] as int? ?? 0,
      contextWindow: json['context_window'] as int? ?? 8192,
      hasLlmOverrides: json['has_llm_overrides'] as bool? ?? false,
      isPinned: json['is_pinned'] as bool? ?? false,
      mode: json['mode'] as String? ?? 'chat',
      agent: _threadAgent(json['agent']),
      latestActiveRun: _threadRun(json['latest_active_run']),
      agents: agents,
      activeRuns: activeRuns,
      pendingApprovals: _contextInt(json['pending_approvals']),
      agentTurnLimit: _contextInt(json['agent_turn_limit']),
      approvalPreset: _approvalPreset(json['approval_preset']),
    );
  }

  /// Last message content for preview
  String get lastMessagePreview {
    if (messages.isEmpty) return 'No messages yet';
    return messages.last.content;
  }
}

class ThreadListItem {
  final String id;
  String title;
  final String? parentId;
  final DateTime createdAt;
  final DateTime updatedAt;
  final int messageCount;
  final bool isGenerating;
  final bool isDiscordThread;
  final String? discordServerName;
  final bool isReachyThread;
  final bool hasLlmOverrides;
  bool isPinned;
  final String mode;
  final ThreadAgentSummary? agent;
  final ThreadRunSummary? latestActiveRun;
  final List<ThreadAgentSummary> agents;
  final List<ThreadRunSummary> activeRuns;
  final int pendingApprovals;
  final int agentTurnLimit;
  String approvalPreset;

  ThreadListItem({
    required this.id,
    required this.title,
    this.parentId,
    required this.createdAt,
    required this.updatedAt,
    required this.messageCount,
    this.isGenerating = false,
    this.isDiscordThread = false,
    this.discordServerName,
    this.isReachyThread = false,
    this.hasLlmOverrides = false,
    this.isPinned = false,
    this.mode = 'chat',
    this.agent,
    this.latestActiveRun,
    this.agents = const [],
    this.activeRuns = const [],
    this.pendingApprovals = 0,
    this.agentTurnLimit = 0,
    this.approvalPreset = 'effectful',
  });

  factory ThreadListItem.fromJson(Map<String, dynamic> json) {
    final agents = _threadAgents(json['agents'], json['agent']);
    final activeRuns = _threadRuns(
      json['active_runs'],
      json['latest_active_run'],
    );
    return ThreadListItem(
      id: json['id'] as String,
      title: json['title'] as String,
      parentId: json['parent_id'] as String?,
      createdAt: DateTime.parse(json['created_at'] as String),
      updatedAt: DateTime.parse(json['updated_at'] as String),
      messageCount: json['message_count'] as int? ?? 0,
      isGenerating: json['is_generating'] as bool? ?? false,
      isDiscordThread: json['is_discord_thread'] as bool? ?? false,
      discordServerName: json['discord_server_name'] as String?,
      isReachyThread: json['is_reachy_thread'] as bool? ?? false,
      hasLlmOverrides: json['has_llm_overrides'] as bool? ?? false,
      isPinned: json['is_pinned'] as bool? ?? false,
      mode: json['mode'] as String? ?? 'chat',
      agent: _threadAgent(json['agent']),
      latestActiveRun: _threadRun(json['latest_active_run']),
      agents: agents,
      activeRuns: activeRuns,
      pendingApprovals: _contextInt(json['pending_approvals']),
      agentTurnLimit: _contextInt(json['agent_turn_limit']),
      approvalPreset: _approvalPreset(json['approval_preset']),
    );
  }
}

class ThreadAgentSummary {
  final String id, name, status, executionMode;
  final String? activeVersionId;
  final String mentionName;
  final bool isModerator;
  final bool isSystem;
  const ThreadAgentSummary({
    required this.id,
    required this.name,
    required this.status,
    required this.executionMode,
    this.activeVersionId,
    this.mentionName = '',
    this.isModerator = false,
    this.isSystem = false,
  });
}

class ThreadRunSummary {
  final String id, status, mode;
  final String? agentId, agentName, agentHandle;
  final String? inputMessageId;
  final String? outputSummary;
  const ThreadRunSummary({
    required this.id,
    required this.status,
    required this.mode,
    this.agentId,
    this.agentName,
    this.agentHandle,
    this.inputMessageId,
    this.outputSummary,
  });
}

ThreadAgentSummary? _threadAgent(dynamic value) {
  if (value is! Map) return null;
  final j = Map<String, dynamic>.from(value);
  return ThreadAgentSummary(
    id: '${j['id'] ?? ''}',
    name: '${j['name'] ?? 'Agent'}',
    status: '${j['status'] ?? 'unknown'}',
    executionMode: '${j['execution_mode'] ?? 'unknown'}',
    activeVersionId: j['active_version_id']?.toString(),
    mentionName: '${j['handle'] ?? j['mention_name'] ?? ''}',
    isModerator: j['is_moderator'] == true,
    isSystem: j['is_system'] == true,
  );
}

List<ThreadAgentSummary> _threadAgents(dynamic value, dynamic legacy) {
  final raw = value is List && value.isNotEmpty
      ? value
      : (legacy is Map ? [legacy] : const []);
  return raw.whereType<Map>().map((v) => _threadAgent(v)!).toList();
}

List<ThreadRunSummary> _threadRuns(dynamic value, dynamic legacy) {
  final raw = value is List && value.isNotEmpty
      ? value
      : (legacy is Map ? [legacy] : const []);
  return raw.whereType<Map>().map((v) => _threadRun(v)!).toList();
}

ThreadRunSummary? _threadRun(dynamic value) {
  if (value is! Map) return null;
  final j = Map<String, dynamic>.from(value);
  return ThreadRunSummary(
    id: '${j['id'] ?? ''}',
    status: '${j['status'] ?? 'unknown'}',
    mode: '${j['mode'] ?? 'live'}',
    agentId: j['agent_id']?.toString(),
    agentName: j['agent_name']?.toString(),
    agentHandle: (j['agent_handle'] ?? j['handle'])?.toString(),
    inputMessageId: (j['input_message_id'] ?? j['inputMessageId'])?.toString(),
    outputSummary: j['output_summary']?.toString(),
  );
}

class ThreadLlmOverrideSchemaEntry {
  final String label;
  final String type;

  ThreadLlmOverrideSchemaEntry({required this.label, required this.type});

  factory ThreadLlmOverrideSchemaEntry.fromJson(Map<String, dynamic> json) {
    return ThreadLlmOverrideSchemaEntry(
      label: json['label'] as String? ?? '',
      type: json['type'] as String? ?? 'string',
    );
  }
}

class ThreadLlmOverrides {
  final String threadId;
  final Map<String, dynamic> overrides;
  final Map<String, dynamic> defaults;
  final Map<String, ThreadLlmOverrideSchemaEntry> schema;

  ThreadLlmOverrides({
    required this.threadId,
    required this.overrides,
    required this.defaults,
    required this.schema,
  });

  factory ThreadLlmOverrides.fromJson(Map<String, dynamic> json) {
    final schemaRaw = (json['schema'] as Map<String, dynamic>? ?? const {});
    final schema = <String, ThreadLlmOverrideSchemaEntry>{};
    for (final entry in schemaRaw.entries) {
      schema[entry.key] = ThreadLlmOverrideSchemaEntry.fromJson(
        entry.value as Map<String, dynamic>,
      );
    }
    return ThreadLlmOverrides(
      threadId: json['thread_id'] as String,
      overrides: Map<String, dynamic>.from(
        json['overrides'] as Map<String, dynamic>? ?? const {},
      ),
      defaults: Map<String, dynamic>.from(
        json['defaults'] as Map<String, dynamic>? ?? const {},
      ),
      schema: schema,
    );
  }

  bool get isEmpty => overrides.isEmpty;

  /// Resolve the value that the runtime sees for [key] (override or default).
  Object? effectiveValue(String key) {
    if (overrides.containsKey(key)) return overrides[key];
    return defaults[key];
  }

  /// All keys in the schema, in the backend's defined order.
  List<String> get keys => schema.keys.toList(growable: false);
}

class ReachyBinding {
  final bool enabled;
  final String? threadId;
  final String? threadTitle;
  final String wakeWord;
  final String taskQueue;

  ReachyBinding({
    required this.enabled,
    this.threadId,
    this.threadTitle,
    required this.wakeWord,
    required this.taskQueue,
  });

  factory ReachyBinding.fromJson(Map<String, dynamic> json) {
    return ReachyBinding(
      enabled: json['enabled'] as bool? ?? false,
      threadId: json['thread_id'] as String?,
      threadTitle: json['thread_title'] as String?,
      wakeWord: json['wake_word'] as String? ?? 'Reachy',
      taskQueue: json['task_queue'] as String? ?? 'reachy-local',
    );
  }
}

class DiscordThreadLink {
  final String threadId;
  final String guildId;
  final String channelId;
  final String discordThreadId;
  final String discordThreadName;
  final bool isActive;

  DiscordThreadLink({
    required this.threadId,
    required this.guildId,
    required this.channelId,
    required this.discordThreadId,
    required this.discordThreadName,
    required this.isActive,
  });

  factory DiscordThreadLink.fromJson(Map<String, dynamic> json) {
    return DiscordThreadLink(
      threadId: json['thread_id'] as String,
      guildId: json['guild_id'] as String,
      channelId: json['channel_id'] as String,
      discordThreadId: json['discord_thread_id'] as String,
      discordThreadName: json['discord_thread_name'] as String,
      isActive: json['is_active'] as bool? ?? true,
    );
  }
}
