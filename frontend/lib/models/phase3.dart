import 'package:flutter/foundation.dart';

String _text(Object? value) => value?.toString() ?? '';
DateTime? _date(Object? value) => DateTime.tryParse(_text(value))?.toUtc();
Map<String, dynamic> _safeMap(Object? value) {
  if (value is! Map) return const {};
  const blocked = {
    'secret',
    'password',
    'token',
    'api_key',
    'ciphertext',
    'hidden_reasoning',
    'chain_of_thought',
  };
  return Map.unmodifiable({
    for (final entry in value.entries)
      if (!blocked.contains(entry.key.toString().toLowerCase()))
        entry.key.toString(): entry.value,
  });
}

List<String> _strings(Object? value) =>
    value is List ? List.unmodifiable(value.map(_text)) : const [];

@immutable
class HandoffContract {
  final String id, name, sourceCapability, targetCapability;
  final int version, timeoutSeconds, maxDepth;
  final Map<String, dynamic> inputSchema, outputSchema;
  final List<String> targetAllowlist, artifactClassifications;
  final bool isActive;
  final String status;
  final int lifecycleVersion;
  final DateTime? createdAt, updatedAt;
  const HandoffContract({
    required this.id,
    required this.name,
    required this.sourceCapability,
    required this.targetCapability,
    required this.version,
    required this.timeoutSeconds,
    required this.maxDepth,
    this.inputSchema = const {},
    this.outputSchema = const {},
    this.targetAllowlist = const [],
    this.artifactClassifications = const [],
    this.isActive = true,
    this.status = 'draft',
    this.lifecycleVersion = 1,
    this.createdAt,
    this.updatedAt,
  });
  factory HandoffContract.fromJson(Map<String, dynamic> j) => HandoffContract(
    id: _text(j['id']),
    name: _text(j['name']),
    sourceCapability: _text(j['source_capability']),
    targetCapability: _text(j['target_capability']),
    version: (j['version'] as num?)?.toInt() ?? 0,
    timeoutSeconds: (j['timeout_seconds'] as num?)?.toInt() ?? 0,
    maxDepth: (j['max_depth'] as num?)?.toInt() ?? 0,
    inputSchema: _safeMap(j['input_schema']),
    outputSchema: _safeMap(j['output_schema']),
    targetAllowlist: _strings(j['target_allowlist']),
    artifactClassifications: _strings(j['artifact_classifications']),
    isActive: j['is_active'] != false,
    status: _text(j['status']).isEmpty ? 'draft' : _text(j['status']),
    lifecycleVersion: (j['lifecycle_version'] as num?)?.toInt() ?? 1,
    createdAt: _date(j['created_at']),
    updatedAt: _date(j['updated_at']),
  );
}

@immutable
class AgentHandoff {
  final String id, contractId, sourceRunId, targetAgentId, status, responseMode;
  final Map<String, dynamic>? outputPayload;
  final DateTime? acknowledgementDeadline, completionDeadline;
  const AgentHandoff({
    required this.id,
    required this.contractId,
    required this.sourceRunId,
    required this.targetAgentId,
    required this.status,
    required this.responseMode,
    this.outputPayload,
    this.acknowledgementDeadline,
    this.completionDeadline,
  });
  factory AgentHandoff.fromJson(Map<String, dynamic> j) => AgentHandoff(
    id: _text(j['id']),
    contractId: _text(j['contract_id']),
    sourceRunId: _text(j['source_run_id']),
    targetAgentId: _text(j['target_agent_id']),
    status: _text(j['status']),
    responseMode: _text(j['response_mode']),
    outputPayload: j['output_payload'] == null
        ? null
        : _safeMap(j['output_payload']),
    acknowledgementDeadline: _date(j['acknowledgement_deadline']),
    completionDeadline: _date(j['completion_deadline']),
  );
  bool get active =>
      !{'completed', 'timed_out', 'cancelled', 'failed'}.contains(status);
}

@immutable
class SlaStatus {
  final String handoffId, status, workflowStatus;
  final DateTime? acknowledgedAt, completionDeadline;
  const SlaStatus({
    required this.handoffId,
    required this.status,
    required this.workflowStatus,
    this.acknowledgedAt,
    this.completionDeadline,
  });
  factory SlaStatus.fromJson(Map<String, dynamic> j) => SlaStatus(
    handoffId: _text(j['handoff_id']),
    status: _text(j['status']),
    workflowStatus: _text(j['workflow_status']),
    acknowledgedAt: _date(j['acknowledged_at']),
    completionDeadline: _date(j['completion_deadline']),
  );
}

@immutable
class SlaIncident {
  final String id, handoffId, stage, targetType, targetId, status;
  final DateTime? createdAt, firedAt;
  const SlaIncident({
    required this.id,
    required this.handoffId,
    required this.stage,
    required this.targetType,
    required this.targetId,
    required this.status,
    this.createdAt,
    this.firedAt,
  });
  factory SlaIncident.fromJson(Map<String, dynamic> j) => SlaIncident(
    id: _text(j['id']),
    handoffId: _text(j['handoff_id']),
    stage: _text(j['stage']),
    targetType: _text(j['target_type']),
    targetId: _text(j['target_id']),
    status: _text(j['status']),
    createdAt: _date(j['created_at']),
    firedAt: _date(j['fired_at']),
  );
}

@immutable
class Artifact {
  final String id, contentType, sha256, classification;
  final String? runId;
  final int sizeBytes, legalHold;
  final DateTime? retentionUntil, createdAt;
  const Artifact({
    required this.id,
    required this.contentType,
    required this.sha256,
    required this.classification,
    this.runId,
    required this.sizeBytes,
    required this.legalHold,
    this.retentionUntil,
    this.createdAt,
  });
  factory Artifact.fromJson(Map<String, dynamic> j) => Artifact(
    id: _text(j['id']),
    contentType: _text(j['content_type']),
    sha256: _text(j['sha256']),
    classification: _text(j['classification']),
    runId: j['run_id']?.toString(),
    sizeBytes: (j['size_bytes'] as num?)?.toInt() ?? 0,
    legalHold: (j['legal_hold'] as num?)?.toInt() ?? 0,
    retentionUntil: _date(j['retention_until']),
    createdAt: _date(j['created_at']),
  );
  bool get onLegalHold => legalHold != 0;
}

@immutable
class ArtifactTombstone {
  final String id, artifactId, sha256, reason;
  final DateTime? deletedAt;
  const ArtifactTombstone({
    required this.id,
    required this.artifactId,
    required this.sha256,
    required this.reason,
    this.deletedAt,
  });
  factory ArtifactTombstone.fromJson(Map<String, dynamic> j) =>
      ArtifactTombstone(
        id: _text(j['id']),
        artifactId: _text(j['artifact_id']),
        sha256: _text(j['sha256']),
        reason: _text(j['reason']),
        deletedAt: _date(j['deleted_at']),
      );
}

@immutable
class OperationsSummary {
  final int activeRuns, queuedRuns, pendingHandoffs, slaIncidents;
  final Map<String, dynamic> queueHealth;
  const OperationsSummary({
    this.activeRuns = 0,
    this.queuedRuns = 0,
    this.pendingHandoffs = 0,
    this.slaIncidents = 0,
    this.queueHealth = const {},
  });
  factory OperationsSummary.fromJson(Map<String, dynamic> j) =>
      OperationsSummary(
        activeRuns: (j['active_runs'] as num?)?.toInt() ?? 0,
        queuedRuns: (j['queued_runs'] as num?)?.toInt() ?? 0,
        pendingHandoffs: (j['pending_handoffs'] as num?)?.toInt() ?? 0,
        slaIncidents: (j['sla_incidents'] as num?)?.toInt() ?? 0,
        queueHealth: _safeMap(j['queue_health']),
      );
}

@immutable
class PolicyRecommendation {
  final String id, risk, status;
  final Map<String, dynamic> evidence, proposedDiff;
  final String? acceptedDraftId;
  final DateTime? createdAt;
  const PolicyRecommendation({
    required this.id,
    required this.risk,
    required this.status,
    this.evidence = const {},
    this.proposedDiff = const {},
    this.acceptedDraftId,
    this.createdAt,
  });
  factory PolicyRecommendation.fromJson(Map<String, dynamic> j) =>
      PolicyRecommendation(
        id: _text(j['id']),
        risk: _text(j['risk']),
        status: _text(j['status']),
        evidence: _safeMap(j['evidence']),
        proposedDiff: _safeMap(j['proposed_diff']),
        acceptedDraftId: j['accepted_draft_id']?.toString(),
        createdAt: _date(j['created_at']),
      );
}

@immutable
class Phase3Event {
  final int sequence;
  final String type;
  final Map<String, dynamic> payload;
  final DateTime? createdAt;
  const Phase3Event({
    required this.sequence,
    required this.type,
    this.payload = const {},
    this.createdAt,
  });
  factory Phase3Event.fromJson(Map<String, dynamic> j) => Phase3Event(
    sequence:
        (j['sequence'] as num?)?.toInt() ??
        int.tryParse(_text(j['cursor'])) ??
        0,
    type: _text(j['event_type'] ?? j['type']),
    payload: _safeMap(j['payload']),
    createdAt: _date(j['created_at']),
  );
}

@immutable
class ArtifactReference {
  final String id, classification, status;
  const ArtifactReference({
    required this.id,
    required this.classification,
    required this.status,
  });
  factory ArtifactReference.fromJson(Map<String, dynamic> j) =>
      ArtifactReference(
        id: _text(j['id'] ?? j['artifact_id']),
        classification: _text(j['classification']),
        status: _text(j['status']),
      );
}
