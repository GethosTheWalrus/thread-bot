import 'package:threadbot/models/message.dart';

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
  });

  factory Thread.fromJson(Map<String, dynamic> json) {
    final messagesJson = json['messages'] as List<dynamic>? ?? [];
    final messages = messagesJson
        .map((m) => Message.fromJson(m as Map<String, dynamic>))
        .toList();

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
  final bool isDiscordThread;
  final String? discordServerName;
  final bool isReachyThread;
  final bool hasLlmOverrides;
  bool isPinned;

  ThreadListItem({
    required this.id,
    required this.title,
    this.parentId,
    required this.createdAt,
    required this.updatedAt,
    required this.messageCount,
    this.isDiscordThread = false,
    this.discordServerName,
    this.isReachyThread = false,
    this.hasLlmOverrides = false,
    this.isPinned = false,
  });

  factory ThreadListItem.fromJson(Map<String, dynamic> json) {
    return ThreadListItem(
      id: json['id'] as String,
      title: json['title'] as String,
      parentId: json['parent_id'] as String?,
      createdAt: DateTime.parse(json['created_at'] as String),
      updatedAt: DateTime.parse(json['updated_at'] as String),
      messageCount: json['message_count'] as int? ?? 0,
      isDiscordThread: json['is_discord_thread'] as bool? ?? false,
      discordServerName: json['discord_server_name'] as String?,
      isReachyThread: json['is_reachy_thread'] as bool? ?? false,
      hasLlmOverrides: json['has_llm_overrides'] as bool? ?? false,
      isPinned: json['is_pinned'] as bool? ?? false,
    );
  }
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
