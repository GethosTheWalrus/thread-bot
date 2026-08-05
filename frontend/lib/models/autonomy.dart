import 'package:flutter/foundation.dart';

String? _string(Object? value) => value is String ? value : value?.toString();
DateTime? _date(Object? value) {
  final text = _string(value);
  if (text == null) return null;
  return DateTime.tryParse(text)?.toUtc();
}

Map<String, dynamic> _map(Object? value) =>
    value is Map ? Map<String, dynamic>.from(value) : <String, dynamic>{};
List<String> _strings(Object? value) => value is List
    ? value.map(_string).whereType<String>().toList()
    : <String>[];
String _enum(Object? value, String fallback) => _string(value) ?? fallback;

@immutable
class Agent {
  final String id, name, status, executionMode, threadId;
  final String handle;
  final String? threadTitle;
  final bool isModerator;
  final String? description, activeVersionId, templateId;
  final int concurrencyLimit, queueLimit;
  final DateTime? createdAt, updatedAt;
  const Agent({
    required this.id,
    required this.name,
    required this.status,
    required this.executionMode,
    required this.threadId,
    this.handle = '',
    this.threadTitle,
    this.isModerator = false,
    this.description,
    this.activeVersionId,
    this.templateId,
    this.concurrencyLimit = 1,
    this.queueLimit = 100,
    this.createdAt,
    this.updatedAt,
  });
  factory Agent.fromJson(Map<String, dynamic> j) => Agent(
    id: _string(j['id']) ?? '',
    name: _string(j['name']) ?? 'Unnamed agent',
    status: _enum(j['status'], 'unknown'),
    executionMode: _enum(j['execution_mode'], 'unknown'),
    threadId: _string(j['thread_id']) ?? '',
    handle: _string(j['handle'] ?? j['mention_name']) ?? '',
    threadTitle: _string(j['thread_title']),
    isModerator: j['is_moderator'] == true,
    description: _string(j['description']),
    activeVersionId: _string(j['active_version_id']),
    templateId: _string(j['template_id']),
    concurrencyLimit: j['concurrency_limit'] is num
        ? (j['concurrency_limit'] as num).toInt()
        : 1,
    queueLimit: j['queue_limit'] is num
        ? (j['queue_limit'] as num).toInt()
        : 100,
    createdAt: _date(j['created_at']),
    updatedAt: _date(j['updated_at']),
  );
}

class Draft {
  final String id, agentId, configHash, promptTemplate;
  final int optimisticLockVersion, schemaVersion;
  final Map<String, dynamic> config;
  final List<String> toolSelection, skillSelection;
  final List<Map<String, dynamic>> credentialBindings;
  final DateTime? updatedAt;
  const Draft({
    this.id = '',
    this.agentId = '',
    this.configHash = '',
    this.promptTemplate = '',
    this.optimisticLockVersion = 1,
    this.schemaVersion = 1,
    this.config = const {},
    this.toolSelection = const [],
    this.skillSelection = const [],
    this.credentialBindings = const [],
    this.updatedAt,
  });
  factory Draft.fromJson(Map<String, dynamic> j) => Draft(
    id: _string(j['id']) ?? '',
    agentId: _string(j['agent_id']) ?? '',
    configHash: _string(j['config_hash']) ?? '',
    promptTemplate: _string(j['prompt_template']) ?? '',
    optimisticLockVersion: (j['optimistic_lock_version'] ?? j['version']) is num
        ? ((j['optimistic_lock_version'] ?? j['version']) as num).toInt()
        : 1,
    schemaVersion: j['schema_version'] is num
        ? (j['schema_version'] as num).toInt()
        : 1,
    config: _map(j['config']),
    toolSelection: _strings(j['tool_selection']),
    skillSelection: _strings(j['skill_selection']),
    credentialBindings: (j['credential_bindings'] is List)
        ? (j['credential_bindings'] as List)
              .whereType<Map>()
              .map((x) => Map<String, dynamic>.from(x))
              .toList()
        : const [],
    updatedAt: _date(j['updated_at']),
  );
}

class Version {
  final String id, agentId, configHash, promptTemplate;
  final int version;
  final Map<String, dynamic> config;
  final List<String> toolSelection, skillSelection;
  const Version({
    this.id = '',
    this.agentId = '',
    this.configHash = '',
    this.promptTemplate = '',
    this.version = 0,
    this.config = const {},
    this.toolSelection = const [],
    this.skillSelection = const [],
  });
  factory Version.fromJson(Map<String, dynamic> j) => Version(
    id: _string(j['id']) ?? '',
    agentId: _string(j['agent_id']) ?? '',
    configHash: _string(j['config_hash']) ?? '',
    promptTemplate: _string(j['prompt_template']) ?? '',
    version: j['version'] is num ? (j['version'] as num).toInt() : 0,
    config: _map(j['config']),
    toolSelection: _strings(j['tool_selection']),
    skillSelection: _strings(j['skill_selection']),
  );
}

class Trigger {
  final String id, type;
  final Map<String, dynamic> config;
  final bool active;
  const Trigger({
    this.id = '',
    this.type = 'unknown',
    this.config = const {},
    this.active = true,
  });
  factory Trigger.fromJson(Map<String, dynamic> j) => Trigger(
    id: _string(j['id']) ?? '',
    type: _enum(j['trigger_type'], 'unknown'),
    config: _map(j['config']),
    active: j['is_active'] != false,
  );
}

class Run {
  final String id, agentId, agentVersionId, threadId, status, mode;
  final String route;
  final String? inputMessageId;
  final String? agentName, agentHandle;
  final String? outputSummary, triggerEventId;
  final DateTime? queuedAt, startedAt, completedAt;
  const Run({
    this.id = '',
    this.agentId = '',
    this.agentVersionId = '',
    this.threadId = '',
    this.status = 'unknown',
    this.mode = 'unknown',
    this.route = '',
    this.inputMessageId,
    this.agentName,
    this.agentHandle,
    this.outputSummary,
    this.triggerEventId,
    this.queuedAt,
    this.startedAt,
    this.completedAt,
  });
  factory Run.fromJson(Map<String, dynamic> j) => Run(
    id: _string(j['id']) ?? '',
    agentId: _string(j['agent_id']) ?? '',
    agentVersionId: _string(j['agent_version_id']) ?? '',
    threadId: _string(j['thread_id']) ?? '',
    status: _enum(j['status'], 'unknown'),
    mode: _enum(j['mode'], 'unknown'),
    route: _string(j['route']) ?? '',
    inputMessageId: _string(j['input_message_id'] ?? j['inputMessageId']),
    agentName: _string(j['agent_name']),
    agentHandle: _string(j['agent_handle'] ?? j['handle']),
    outputSummary: _string(j['output_summary']),
    triggerEventId: _string(j['trigger_event_id']),
    queuedAt: _date(j['queued_at']),
    startedAt: _date(j['started_at']),
    completedAt: _date(j['completed_at']),
  );

  Run copyWith({
    String? inputMessageId,
    String? agentName,
    String? agentHandle,
  }) => Run(
    id: id,
    agentId: agentId,
    agentVersionId: agentVersionId,
    threadId: threadId,
    status: status,
    mode: mode,
    route: route,
    inputMessageId: inputMessageId ?? this.inputMessageId,
    agentName: agentName ?? this.agentName,
    agentHandle: agentHandle ?? this.agentHandle,
    outputSummary: outputSummary,
    triggerEventId: triggerEventId,
    queuedAt: queuedAt,
    startedAt: startedAt,
    completedAt: completedAt,
  );
}

@immutable
class ActiveRunPresentation {
  final Run run;
  final List<RunEvent> events;

  const ActiveRunPresentation({required this.run, this.events = const []});

  String get id => run.id;
  String? get inputMessageId => run.inputMessageId;
}

class RunEvent {
  final int sequence;
  final String type;
  final Map<String, dynamic> payload;
  final DateTime? createdAt;
  const RunEvent({
    this.sequence = 0,
    this.type = 'unknown',
    this.payload = const {},
    this.createdAt,
  });
  factory RunEvent.fromJson(Map<String, dynamic> j) => RunEvent(
    sequence: j['sequence'] is num
        ? (j['sequence'] as num).toInt()
        : int.tryParse(_string(j['cursor']) ?? '0') ?? 0,
    type: _enum(j['event_type'] ?? j['type'], 'unknown'),
    payload: _map(j['payload']),
    createdAt: _date(j['created_at']),
  );
}

class AuditEntry {
  final String id, type, resourceType;
  final Map<String, dynamic> metadata;
  final DateTime? createdAt;
  const AuditEntry({
    this.id = '',
    this.type = 'unknown',
    this.resourceType = 'unknown',
    this.metadata = const {},
    this.createdAt,
  });
  factory AuditEntry.fromJson(Map<String, dynamic> j) => AuditEntry(
    id: _string(j['id']) ?? '',
    type: _enum(j['event_type'], 'unknown'),
    resourceType: _enum(j['resource_type'], 'unknown'),
    metadata: _map(j['metadata'] ?? j['payload']),
    createdAt: _date(j['created_at']),
  );
}

@immutable
class HeartbeatStatus {
  final String agentId;
  final bool enabled;
  final int minWakeSeconds;
  final int maxWakeSeconds;
  final double idleBackoffFactor;
  final int revision;
  final String operationalStatus;
  final String? workflowId;
  final DateTime? lastWakeAt;
  final DateTime? lastCompletedAt;
  final DateTime? nextWakeAt;
  final String? lastDecision;
  final String? lastRunId;
  final int consecutiveNoops;
  final String? lastError;
  final DateTime? updatedAt;
  const HeartbeatStatus({
    required this.agentId,
    this.enabled = false,
    this.minWakeSeconds = 300,
    this.maxWakeSeconds = 3600,
    this.idleBackoffFactor = 2.0,
    this.revision = 1,
    this.operationalStatus = 'disabled',
    this.workflowId,
    this.lastWakeAt,
    this.lastCompletedAt,
    this.nextWakeAt,
    this.lastDecision,
    this.lastRunId,
    this.consecutiveNoops = 0,
    this.lastError,
    this.updatedAt,
  });
  factory HeartbeatStatus.fromJson(Map<String, dynamic> j) {
    final backoff = j['idle_backoff_factor'];
    return HeartbeatStatus(
      agentId: _string(j['agent_id']) ?? '',
      enabled: j['enabled'] is bool ? j['enabled'] as bool : false,
      minWakeSeconds: j['min_wake_seconds'] is num
          ? (j['min_wake_seconds'] as num).toInt()
          : 300,
      maxWakeSeconds: j['max_wake_seconds'] is num
          ? (j['max_wake_seconds'] as num).toInt()
          : 3600,
      idleBackoffFactor: backoff is num
          ? (backoff).toDouble()
          : double.tryParse(_string(backoff) ?? '2.0') ?? 2.0,
      revision: j['revision'] is num ? (j['revision'] as num).toInt() : 1,
      operationalStatus: _enum(j['operational_status'], 'disabled'),
      workflowId: _string(j['workflow_id']),
      lastWakeAt: _date(j['last_wake_at']),
      lastCompletedAt: _date(j['last_completed_at']),
      nextWakeAt: _date(j['next_wake_at']),
      lastDecision: _string(j['last_decision']),
      lastRunId: _string(j['last_run_id']),
      consecutiveNoops: j['consecutive_noops'] is num
          ? (j['consecutive_noops'] as num).toInt()
          : 0,
      lastError: _string(j['last_error']),
      updatedAt: _date(j['updated_at']),
    );
  }
  String get statusLabel {
    switch (operationalStatus) {
      case 'disabled':
        return 'Off';
      case 'scheduled':
        return nextWakeAt != null
            ? 'Next wake ${_relative(nextWakeAt!)}'
            : 'Scheduled';
      case 'evaluating':
        return 'Evaluating';
      case 'paused':
        return 'Paused';
      case 'blocked_mode':
        return 'Blocked (thread not agent mode)';
      case 'blocked_archived':
        return 'Blocked (archived)';
      case 'blocked_global':
        return 'Blocked (autonomy disabled)';
      case 'error':
        return 'Error';
      default:
        return operationalStatus;
    }
  }

  String _relative(DateTime target) {
    final delta = target.difference(DateTime.now().toUtc());
    if (delta.isNegative) return 'now';
    final mins = delta.inMinutes;
    if (mins < 1) return 'in ${delta.inSeconds}s';
    if (mins < 60) return 'in $mins min';
    final hours = delta.inHours;
    if (hours < 24) return 'in ${hours}h';
    return 'in ${delta.inDays}d';
  }
}

class HeartbeatConfig {
  final bool enabled;
  final int minWakeSeconds;
  final int maxWakeSeconds;
  final double idleBackoffFactor;
  final int? expectedRevision;
  const HeartbeatConfig({
    required this.enabled,
    this.minWakeSeconds = 300,
    this.maxWakeSeconds = 3600,
    this.idleBackoffFactor = 2.0,
    this.expectedRevision,
  });
  Map<String, dynamic> toJson() => {
    'enabled': enabled,
    'min_wake_seconds': minWakeSeconds,
    'max_wake_seconds': maxWakeSeconds,
    'idle_backoff_factor': idleBackoffFactor,
    if (expectedRevision != null) 'expected_revision': expectedRevision,
  };
}
