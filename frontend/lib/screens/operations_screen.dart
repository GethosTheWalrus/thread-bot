import 'dart:async';
import 'dart:convert';
import 'package:flutter/material.dart';
import 'package:threadbot/models/phase2.dart';
import 'package:threadbot/services/autonomy_api.dart';
import 'package:threadbot/services/autonomy_socket.dart';
import 'package:threadbot/services/phase2_api.dart';
import 'package:threadbot/models/phase3.dart';
import 'package:threadbot/services/phase3_api.dart';
import 'package:threadbot/services/phase4_api.dart';
import 'package:threadbot/widgets/phase4_panels.dart';

class OperationsScreen extends StatefulWidget {
  final AutonomyApiService baseApi;
  final String? initialSection;
  const OperationsScreen({
    super.key,
    required this.baseApi,
    this.initialSection,
  });
  @override
  State<OperationsScreen> createState() => _OperationsState();
}

class _OperationsState extends State<OperationsScreen> {
  late final Phase2ApiService api = Phase2ApiService(widget.baseApi);
  late final Phase3ApiService phase3 = Phase3ApiService(widget.baseApi);
  late final Phase4ApiService phase4 = Phase4ApiService(widget.baseApi);
  List<Phase2Record> connectors = [],
      credentials = [],
      bindings = [],
      profiles = [],
      deadLetters = [];
  List<Phase2Event> events = [];
  List<HandoffContract> contracts = [];
  List<AgentHandoff> handoffs = [];
  List<PolicyRecommendation> recommendations = [];
  OperationsSummary? summary;
  List<SlaIncident> incidents = [];
  List<Artifact> artifacts = [];
  List<ArtifactTombstone> tombstones = [];
  String? error;
  bool loading = false;
  final search = TextEditingController();
  AutonomySocket<Phase2Event>? socket;
  StreamSubscription<Phase2Event>? sub;
  @override
  void initState() {
    super.initState();
    search.addListener(() {
      if (mounted) setState(() {});
    });
    load();
    socket = AutonomySocket(
      uriBuilder: (after) => widget.baseApi.websocketUri(
        '/api/events/ws',
        query: {'after': '$after'},
      ),
      decode: Phase2Event.fromJson,
      strictSequence: false,
    );
    sub = socket!.stream.listen((e) {
      if (mounted) setState(() => events = [...events, e]);
    });
    socket!.connect();
  }

  Future<void> load() async {
    if (mounted)
      setState(() {
        loading = true;
        error = null;
      });
    try {
      final values = await Future.wait([
        api.connectors(),
        api.credentials(),
        api.bindings(),
        api.notificationProfiles(),
        api.deadLetters(),
        phase3.contracts(),
        phase3.handoffs(),
        phase3.recommendations(),
        phase3.operationsSummary(),
        phase3.slaIncidents(),
        phase3.artifacts(),
        phase3.tombstones(),
      ]);
      if (mounted)
        setState(() {
          connectors = values[0] as List<Phase2Record>;
          credentials = values[1] as List<Phase2Record>;
          bindings = values[2] as List<Phase2Record>;
          profiles = values[3] as List<Phase2Record>;
          deadLetters = values[4] as List<Phase2Record>;
          contracts = (values[5] as CursorPage<HandoffContract>).items;
          handoffs = (values[6] as CursorPage<AgentHandoff>).items;
          recommendations = values[7] as List<PolicyRecommendation>;
          summary = values[8] as OperationsSummary;
          incidents = (values[9] as CursorPage<SlaIncident>).items;
          artifacts = (values[10] as CursorPage<Artifact>).items;
          tombstones = values[11] as List<ArtifactTombstone>;
        });
    } catch (e) {
      if (mounted) setState(() => error = '$e');
    } finally {
      if (mounted) setState(() => loading = false);
    }
  }

  Future<void> _connectorDialog() async {
    final name = TextEditingController(),
        type = TextEditingController(text: 'webhook');
    try {
      final ok = await showDialog<bool>(
        context: context,
        builder: (c) => AlertDialog(
          title: const Text('New connector'),
          content: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              TextField(
                controller: name,
                decoration: const InputDecoration(labelText: 'Name'),
              ),
              TextField(
                controller: type,
                decoration: const InputDecoration(labelText: 'Type'),
              ),
            ],
          ),
          actions: [
            TextButton(
              onPressed: () => Navigator.pop(c),
              child: const Text('Cancel'),
            ),
            FilledButton(
              onPressed: () => Navigator.pop(c, true),
              child: const Text('Create'),
            ),
          ],
        ),
      );
      if (ok == true && name.text.trim().isNotEmpty) {
        await api.createConnector({
          'name': name.text.trim(),
          'connector_type': type.text.trim(),
          'config': {},
        });
        await load();
      }
    } catch (e) {
      if (mounted)
        ScaffoldMessenger.of(
          context,
        ).showSnackBar(SnackBar(content: Text('$e')));
    } finally {
      name.dispose();
      type.dispose();
    }
  }

  Future<void> _credentialDialog({Phase2Record? existing}) async {
    final name = TextEditingController(text: existing?.name),
        provider = TextEditingController(),
        secret = TextEditingController();
    try {
      final ok = await showDialog<bool>(
        context: context,
        builder: (c) => AlertDialog(
          title: Text(
            existing == null ? 'New credential' : 'Rotate credential',
          ),
          content: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              TextField(
                controller: name,
                decoration: const InputDecoration(labelText: 'Name'),
              ),
              TextField(
                controller: provider,
                decoration: const InputDecoration(labelText: 'Provider'),
              ),
              TextField(
                controller: secret,
                obscureText: true,
                decoration: const InputDecoration(labelText: 'Secret'),
              ),
            ],
          ),
          actions: [
            TextButton(
              onPressed: () => Navigator.pop(c),
              child: const Text('Cancel'),
            ),
            FilledButton(
              onPressed: () => Navigator.pop(c, true),
              child: const Text('Save'),
            ),
          ],
        ),
      );
      final value = secret.text;
      if (ok == true && value.isNotEmpty) {
        if (existing == null)
          await api.createCredential(
            name.text.trim(),
            provider.text.trim(),
            value,
          );
        else
          await api.rotateCredential(
            existing.id,
            name.text.trim(),
            provider.text.trim(),
            value,
          );
        await load();
      }
    } catch (e) {
      if (mounted)
        ScaffoldMessenger.of(
          context,
        ).showSnackBar(SnackBar(content: Text('$e')));
    } finally {
      name.dispose();
      provider.dispose();
      secret.dispose();
    }
  }

  Future<void> _bindingDialog() async {
    final credential = TextEditingController(), key = TextEditingController();
    try {
      final ok = await showDialog<bool>(
        context: context,
        builder: (c) => AlertDialog(
          title: const Text('New credential binding'),
          content: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              TextField(
                controller: credential,
                decoration: const InputDecoration(labelText: 'Credential ID'),
              ),
              TextField(
                controller: key,
                decoration: const InputDecoration(labelText: 'Binding key'),
              ),
            ],
          ),
          actions: [
            TextButton(
              onPressed: () => Navigator.pop(c),
              child: const Text('Cancel'),
            ),
            FilledButton(
              onPressed: () => Navigator.pop(c, true),
              child: const Text('Create'),
            ),
          ],
        ),
      );
      if (ok == true) {
        await api.createBinding({
          'credential_id': credential.text.trim(),
          'binding_key': key.text.trim(),
          'constraints': {},
        });
        await load();
      }
    } catch (e) {
      if (mounted)
        ScaffoldMessenger.of(
          context,
        ).showSnackBar(SnackBar(content: Text('$e')));
    } finally {
      credential.dispose();
      key.dispose();
    }
  }

  Future<void> _profileDialog() async {
    final name = TextEditingController();
    try {
      final ok = await showDialog<bool>(
        context: context,
        builder: (c) => AlertDialog(
          title: const Text('New notification profile'),
          content: TextField(
            controller: name,
            decoration: const InputDecoration(labelText: 'Name'),
          ),
          actions: [
            TextButton(
              onPressed: () => Navigator.pop(c),
              child: const Text('Cancel'),
            ),
            FilledButton(
              onPressed: () => Navigator.pop(c, true),
              child: const Text('Create'),
            ),
          ],
        ),
      );
      if (ok == true && name.text.trim().isNotEmpty) {
        await api.createNotificationProfile({
          'name': name.text.trim(),
          'routes': [],
        });
        await load();
      }
    } catch (e) {
      if (mounted)
        ScaffoldMessenger.of(
          context,
        ).showSnackBar(SnackBar(content: Text('$e')));
    } finally {
      name.dispose();
    }
  }

  Future<void> _routeDialog(Phase2Record profile) async {
    final name = TextEditingController(),
        channel = TextEditingController(text: 'in_app');
    try {
      final ok = await showDialog<bool>(
        context: context,
        builder: (c) => AlertDialog(
          title: Text('Add route to ${profile.name}'),
          content: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              TextField(
                controller: name,
                decoration: const InputDecoration(labelText: 'Name'),
              ),
              TextField(
                controller: channel,
                decoration: const InputDecoration(labelText: 'Channel'),
              ),
            ],
          ),
          actions: [
            TextButton(
              onPressed: () => Navigator.pop(c),
              child: const Text('Cancel'),
            ),
            FilledButton(
              onPressed: () => Navigator.pop(c, true),
              child: const Text('Create'),
            ),
          ],
        ),
      );
      if (ok == true) {
        await api.createNotificationRoute(profile.id, {
          'name': name.text.trim(),
          'channel': channel.text.trim(),
          'config': {},
          'filters': {},
        });
        await load();
      }
    } catch (e) {
      if (mounted)
        ScaffoldMessenger.of(
          context,
        ).showSnackBar(SnackBar(content: Text('$e')));
    } finally {
      name.dispose();
      channel.dispose();
    }
  }

  Future<void> _policyDialog() async {
    final rules = TextEditingController(text: '{}');
    try {
      await showDialog<void>(
        context: context,
        builder: (c) => AlertDialog(
          title: const Text('Explain policy'),
          content: TextField(
            controller: rules,
            minLines: 4,
            maxLines: 8,
            decoration: const InputDecoration(labelText: 'Rules JSON'),
          ),
          actions: [
            TextButton(
              onPressed: () => Navigator.pop(c),
              child: const Text('Cancel'),
            ),
            FilledButton(
              onPressed: () async {
                try {
                  final result = await api.explainPolicy({
                    'rules': jsonDecode(rules.text),
                    'policy_version': 'default',
                  });
                  if (!c.mounted) return;
                  if (!mounted) return;
                  Navigator.pop(c);
                  await showDialog<void>(
                    context: context,
                    builder: (d) => AlertDialog(
                      title: const Text('Policy explanation'),
                      content: SelectableText(
                        const JsonEncoder.withIndent('  ').convert(result),
                      ),
                      actions: [
                        TextButton(
                          onPressed: () => Navigator.pop(d),
                          child: const Text('Close'),
                        ),
                      ],
                    ),
                  );
                } catch (e) {
                  if (c.mounted)
                    ScaffoldMessenger.of(
                      c,
                    ).showSnackBar(SnackBar(content: Text('$e')));
                }
              },
              child: const Text('Explain'),
            ),
          ],
        ),
      );
    } finally {
      rules.dispose();
    }
  }

  @override
  void dispose() {
    search.dispose();
    sub?.cancel();
    socket?.dispose();
    super.dispose();
  }

  Widget group(
    String title,
    List<Phase2Record> values, {
    bool retry = false,
    VoidCallback? add,
    VoidCallback? rotate,
    void Function(Phase2Record)? route,
  }) => Card(
    child: ExpansionTile(
      title: Row(
        children: [
          Expanded(child: Text('$title (${values.length})')),
          if (add != null)
            IconButton(onPressed: add, icon: const Icon(Icons.add)),
        ],
      ),
      children: values.isEmpty
          ? [const ListTile(title: Text('None'))]
          : [
              for (final value in values)
                ListTile(
                  title: Text(value.name.isEmpty ? value.id : value.name),
                  subtitle: Text('${value.type} ${value.status}'),
                  trailing: retry
                      ? TextButton(
                          onPressed: () async {
                            await api.retryDeadLetter(value.id);
                            load();
                          },
                          child: const Text('Retry'),
                        )
                      : rotate != null
                      ? TextButton(
                          onPressed: () => rotate(),
                          child: const Text('Rotate'),
                        )
                      : route != null
                      ? TextButton(
                          onPressed: () => route(value),
                          child: const Text('Route'),
                        )
                      : null,
                ),
            ],
    ),
  );
  @override
  Widget build(BuildContext context) => Scaffold(
    appBar: AppBar(
      title: const Text('Operations'),
      actions: [
        IconButton(
          onPressed: _policyDialog,
          icon: const Icon(Icons.policy_outlined),
        ),
        IconButton(onPressed: load, icon: const Icon(Icons.refresh)),
      ],
    ),
    body: error != null
        ? Center(child: Text(error!))
        : ListView(
            padding: const EdgeInsets.all(16),
            children: [
              TextField(
                controller: search,
                decoration: const InputDecoration(
                  prefixIcon: Icon(Icons.search),
                  hintText: 'Search operations',
                ),
              ),
              if (loading) const LinearProgressIndicator(),
              group(
                'Connectors',
                connectors.where((x) => _matches(x)).toList(),
                add: _connectorDialog,
              ),
              group(
                'Credentials',
                credentials.where((x) => _matches(x)).toList(),
                add: () => _credentialDialog(),
                rotate: credentials.isEmpty
                    ? null
                    : () => _credentialDialog(existing: credentials.first),
              ),
              group(
                'Credential bindings',
                bindings.where((x) => _matches(x)).toList(),
                add: _bindingDialog,
              ),
              group(
                'Notification profiles',
                profiles.where((x) => _matches(x)).toList(),
                add: _profileDialog,
                route: (profile) => _routeDialog(profile),
              ),
              group('Dead letters', deadLetters, retry: true),
              _phase3Section(
                'Handoff contracts',
                'handoff-contracts',
                contracts.isEmpty
                    ? const Text('No handoff contracts are registered.')
                    : Column(
                        children: [
                          Align(
                            alignment: Alignment.centerLeft,
                            child: FilledButton.icon(
                              onPressed: _contractDialog,
                              icon: const Icon(Icons.add),
                              label: const Text('New contract'),
                            ),
                          ),
                          for (final item in contracts)
                            ListTile(
                              leading: const Icon(Icons.account_tree_outlined),
                              title: Text('${item.name} v${item.version}'),
                              subtitle: Text(
                                '${item.sourceCapability} → ${item.targetCapability} • ${item.status} • v${item.lifecycleVersion}',
                              ),
                              trailing: Wrap(
                                children: [
                                  TextButton(
                                    onPressed: () => _versionsDialog(item),
                                    child: const Text('Versions'),
                                  ),
                                  if (item.status == 'draft')
                                    TextButton(
                                      onPressed: () =>
                                          _validateContractDialog(item),
                                      child: const Text('Validate'),
                                    ),
                                  if (item.status == 'draft')
                                    TextButton(
                                      onPressed: () =>
                                          _contractDialog(existing: item),
                                      child: const Text('Edit'),
                                    ),
                                  if (item.status == 'draft')
                                    FilledButton(
                                      onPressed: () =>
                                          _contractAction(item, true),
                                      child: const Text('Activate'),
                                    ),
                                  if (item.status == 'active')
                                    TextButton(
                                      onPressed: () =>
                                          _contractAction(item, false),
                                      child: const Text('Archive'),
                                    ),
                                ],
                              ),
                            ),
                        ],
                      ),
              ),
              _phase3Section(
                'Active handoffs / SLA',
                'active-handoffs',
                handoffs.isEmpty
                    ? const Text('No handoffs are currently active.')
                    : Column(
                        children: [
                          for (final item in handoffs.where((x) => x.active))
                            ListTile(
                              leading: const Icon(Icons.pending_actions),
                              title: Text(
                                '${item.status} • ${item.responseMode}',
                              ),
                              subtitle: Text(
                                'Run ${item.sourceRunId}\nAcknowledgement: ${item.acknowledgementDeadline ?? '—'}\nCompletion: ${item.completionDeadline ?? '—'}',
                              ),
                              trailing: item.status == 'pending'
                                  ? TextButton(
                                      onPressed: () async {
                                        await phase3.acknowledge(item.id);
                                        await load();
                                      },
                                      child: const Text('Acknowledge'),
                                    )
                                  : null,
                            ),
                        ],
                      ),
              ),
              _phase3Section(
                'Task queues',
                'task-queues',
                summary == null
                    ? const CircularProgressIndicator()
                    : Column(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                          Text(
                            'Active runs: ${summary!.activeRuns}  •  queued: ${summary!.queuedRuns}',
                          ),
                          for (final entry in summary!.queueHealth.entries)
                            ListTile(
                              dense: true,
                              title: Text(entry.key),
                              subtitle: Text('${entry.value}'),
                              trailing: const Icon(Icons.check_circle_outline),
                            ),
                        ],
                      ),
              ),
              _phase3Section(
                'Artifact retention / legal holds / tombstones',
                'artifacts',
                Column(
                  children: [
                    for (final artifact in artifacts)
                      ListTile(
                        title: Text(
                          '${artifact.classification} • ${artifact.contentType}',
                        ),
                        subtitle: Text(
                          '${artifact.sizeBytes} bytes • retention ${artifact.retentionUntil ?? 'none'}',
                        ),
                        trailing: Wrap(
                          children: [
                            TextButton(
                              onPressed: () async {
                                await phase3.setLegalHold(
                                  artifact.id,
                                  !artifact.onLegalHold,
                                );
                                await load();
                              },
                              child: Text(
                                artifact.onLegalHold
                                    ? 'Release hold'
                                    : 'Legal hold',
                              ),
                            ),
                            IconButton(
                              tooltip: 'Set retention',
                              onPressed: () => _retentionDialog(artifact),
                              icon: const Icon(Icons.schedule),
                            ),
                          ],
                        ),
                      ),
                    if (tombstones.isNotEmpty)
                      ExpansionTile(
                        title: Text('Tombstones (${tombstones.length})'),
                        children: [
                          for (final tombstone in tombstones)
                            ListTile(
                              title: Text(tombstone.artifactId),
                              subtitle: Text(
                                '${tombstone.reason} • ${tombstone.deletedAt ?? ''}',
                              ),
                            ),
                        ],
                      ),
                  ],
                ),
              ),
              _phase3Section(
                'SLA incidents',
                'sla-incidents',
                incidents.isEmpty
                    ? const Text('No SLA incidents.')
                    : Column(
                        children: [
                          for (final incident in incidents)
                            ListTile(
                              title: Text(
                                '${incident.stage} • ${incident.status}',
                              ),
                              subtitle: Text(
                                'Handoff ${incident.handoffId} → ${incident.targetType}:${incident.targetId}',
                              ),
                            ),
                        ],
                      ),
              ),
              _recommendationSection(),
              Phase4OperationsPanel(api: phase4),
              if (events.isNotEmpty)
                Card(
                  child: ExpansionTile(
                    title: Text('Workspace events (${events.length})'),
                    children: [
                      for (final event in events.take(20))
                        ListTile(
                          title: Text(event.type),
                          leading: Text('${event.cursor}'),
                        ),
                    ],
                  ),
                ),
            ],
          ),
  );
  bool _matches(Phase2Record x) =>
      search.text.trim().isEmpty ||
      '${x.name} ${x.type} ${x.status}'.toLowerCase().contains(
        search.text.toLowerCase(),
      );

  Widget _phase3Section(String title, String id, Widget child) => Card(
    key: ValueKey(id),
    child: ExpansionTile(
      title: Text(title),
      initiallyExpanded: widget.initialSection == id,
      children: [
        Padding(
          padding: const EdgeInsets.fromLTRB(16, 0, 16, 12),
          child: Align(alignment: Alignment.centerLeft, child: child),
        ),
      ],
    ),
  );

  Widget _recommendationSection() => Card(
    key: const ValueKey('policy-recommendations'),
    child: ExpansionTile(
      title: Text('Policy recommendations (${recommendations.length})'),
      initiallyExpanded: widget.initialSection == 'policy-recommendations',
      children: recommendations.isEmpty
          ? [const ListTile(title: Text('No recommendations.'))]
          : [
              for (final recommendation in recommendations)
                ListTile(
                  title: Text(
                    '${recommendation.risk} • ${recommendation.status}',
                  ),
                  subtitle: Text(
                    'Evidence: ${recommendation.evidence}\nDiff: ${const JsonEncoder.withIndent('  ').convert(recommendation.proposedDiff)}',
                  ),
                  isThreeLine: true,
                  trailing: recommendation.status == 'pending'
                      ? Wrap(
                          children: [
                            TextButton(
                              onPressed: () =>
                                  _decideRecommendation(recommendation, false),
                              child: const Text('Reject'),
                            ),
                            FilledButton(
                              onPressed: () =>
                                  _decideRecommendation(recommendation, true),
                              child: const Text('Accept'),
                            ),
                          ],
                        )
                      : null,
                ),
            ],
    ),
  );

  Future<void> _decideRecommendation(
    PolicyRecommendation recommendation,
    bool accept,
  ) async {
    final confirmed = await showDialog<bool>(
      context: context,
      builder: (c) => AlertDialog(
        title: Text(
          accept
              ? 'Accept policy recommendation?'
              : 'Reject policy recommendation?',
        ),
        content: SingleChildScrollView(
          child: Text(
            '${accept ? 'This will apply the proposed policy diff.' : 'The recommendation will remain unapplied.'}\n\nDiff:\n${const JsonEncoder.withIndent('  ').convert(recommendation.proposedDiff)}',
          ),
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(c, false),
            child: const Text('Cancel'),
          ),
          FilledButton(
            onPressed: () => Navigator.pop(c, true),
            child: Text(accept ? 'Confirm accept' : 'Confirm reject'),
          ),
        ],
      ),
    );
    if (confirmed != true || !mounted) return;
    try {
      await phase3.decideRecommendation(recommendation.id, accept: accept);
      await load();
    } catch (e) {
      if (mounted)
        ScaffoldMessenger.of(
          context,
        ).showSnackBar(SnackBar(content: Text('$e')));
    }
  }

  Future<void> _contractDialog({HandoffContract? existing}) async {
    final name = TextEditingController(text: existing?.name),
        source = TextEditingController(text: existing?.sourceCapability),
        target = TextEditingController(text: existing?.targetCapability),
        schema = TextEditingController(
          text: const JsonEncoder.withIndent(
            '  ',
          ).convert(existing?.inputSchema ?? {'type': 'object'}),
        ),
        timeout = TextEditingController(
          text: '${existing?.timeoutSeconds ?? 300}',
        ),
        depth = TextEditingController(text: '${existing?.maxDepth ?? 3}');
    try {
      final save = await showDialog<bool>(
        context: context,
        builder: (c) => AlertDialog(
          title: Text(
            existing == null ? 'New handoff contract' : 'Edit handoff contract',
          ),
          content: SingleChildScrollView(
            child: Column(
              mainAxisSize: MainAxisSize.min,
              children: [
                TextField(
                  controller: name,
                  decoration: const InputDecoration(labelText: 'Name'),
                ),
                TextField(
                  controller: source,
                  decoration: const InputDecoration(
                    labelText: 'Source capability',
                  ),
                ),
                TextField(
                  controller: target,
                  decoration: const InputDecoration(
                    labelText: 'Target capability',
                  ),
                ),
                TextField(
                  controller: schema,
                  minLines: 3,
                  maxLines: 8,
                  decoration: const InputDecoration(
                    labelText: 'Input JSON schema',
                  ),
                ),
                TextField(
                  controller: timeout,
                  keyboardType: TextInputType.number,
                  decoration: const InputDecoration(
                    labelText: 'Timeout seconds',
                  ),
                ),
                TextField(
                  controller: depth,
                  keyboardType: TextInputType.number,
                  decoration: const InputDecoration(labelText: 'Maximum depth'),
                ),
              ],
            ),
          ),
          actions: [
            TextButton(
              onPressed: () => Navigator.pop(c, false),
              child: const Text('Cancel'),
            ),
            FilledButton(
              onPressed: () => Navigator.pop(c, true),
              child: const Text('Save'),
            ),
          ],
        ),
      );
      if (save != true || !mounted) return;
      final inputSchema = jsonDecode(schema.text) as Map<String, dynamic>;
      final body = {
        'source_capability': source.text.trim(),
        'target_capability': target.text.trim(),
        'input_schema': inputSchema,
        'timeout_seconds': int.tryParse(timeout.text) ?? 300,
        'max_depth': int.tryParse(depth.text) ?? 3,
        'output_schema': existing?.outputSchema ?? {},
        'target_allowlist': existing?.targetAllowlist ?? [],
        'artifact_classifications': existing?.artifactClassifications ?? [],
      };
      if (existing == null)
        await phase3.createContract({
          'name': name.text.trim(),
          'version': 1,
          ...body,
        });
      else
        await phase3.patchContract(existing.id, {
          'lifecycle_version': existing.lifecycleVersion,
          ...body,
        });
      await load();
    } catch (e) {
      if (mounted)
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(
            content: Text(
              e is ApiException && e.conflict
                  ? 'Contract changed elsewhere; reload and retry.'
                  : '$e',
            ),
          ),
        );
    } finally {
      for (final controller in [name, source, target, schema, timeout, depth])
        controller.dispose();
    }
  }

  Future<void> _contractAction(HandoffContract contract, bool activate) async {
    try {
      if (activate) {
        final result = await phase3.validateContract(contract.id, {});
        if (result['valid'] != true) throw StateError('${result['errors']}');
        await phase3.activateContract(contract.id);
      } else {
        await phase3.archiveContract(contract.id);
      }
      await load();
    } catch (e) {
      if (mounted)
        ScaffoldMessenger.of(
          context,
        ).showSnackBar(SnackBar(content: Text('$e')));
    }
  }

  Future<void> _validateContractDialog(HandoffContract contract) async {
    final payload = TextEditingController(text: '{}');
    try {
      final ok = await showDialog<bool>(
        context: context,
        builder: (c) => AlertDialog(
          title: const Text('Validate handoff payload'),
          content: TextField(
            controller: payload,
            minLines: 3,
            maxLines: 8,
            decoration: const InputDecoration(labelText: 'Input JSON'),
          ),
          actions: [
            TextButton(
              onPressed: () => Navigator.pop(c, false),
              child: const Text('Cancel'),
            ),
            FilledButton(
              onPressed: () => Navigator.pop(c, true),
              child: const Text('Validate'),
            ),
          ],
        ),
      );
      if (ok != true || !mounted) return;
      final result = await phase3.validateContract(
        contract.id,
        Map<String, dynamic>.from(jsonDecode(payload.text) as Map),
      );
      if (mounted)
        showDialog<void>(
          context: context,
          builder: (c) => AlertDialog(
            title: Text(
              result['valid'] == true ? 'Valid payload' : 'Invalid payload',
            ),
            content: Text(result.toString()),
            actions: [
              TextButton(
                onPressed: () => Navigator.pop(c),
                child: const Text('Close'),
              ),
            ],
          ),
        );
    } catch (e) {
      if (mounted)
        ScaffoldMessenger.of(
          context,
        ).showSnackBar(SnackBar(content: Text('$e')));
    } finally {
      payload.dispose();
    }
  }

  Future<void> _versionsDialog(HandoffContract contract) async {
    try {
      final versions = await phase3.contractVersions(contract.id);
      if (!mounted) return;
      showDialog<void>(
        context: context,
        builder: (c) => AlertDialog(
          title: Text('${contract.name} versions'),
          content: SizedBox(
            width: 420,
            child: ListView(
              shrinkWrap: true,
              children: [
                for (final version in versions)
                  ListTile(
                    title: Text('v${version.version} • ${version.status}'),
                    subtitle: Text(
                      'Lifecycle ${version.lifecycleVersion} • ${version.sourceCapability} → ${version.targetCapability}',
                    ),
                  ),
              ],
            ),
          ),
          actions: [
            TextButton(
              onPressed: () => Navigator.pop(c),
              child: const Text('Close'),
            ),
          ],
        ),
      );
    } catch (e) {
      if (mounted)
        ScaffoldMessenger.of(
          context,
        ).showSnackBar(SnackBar(content: Text('$e')));
    }
  }

  Future<void> _retentionDialog(Artifact artifact) async {
    final controller = TextEditingController(
      text: artifact.retentionUntil?.toIso8601String() ?? '',
    );
    try {
      final save = await showDialog<bool>(
        context: context,
        builder: (c) => AlertDialog(
          title: const Text('Set artifact retention'),
          content: TextField(
            controller: controller,
            decoration: const InputDecoration(
              labelText: 'UTC ISO-8601 timestamp',
            ),
          ),
          actions: [
            TextButton(
              onPressed: () => Navigator.pop(c, false),
              child: const Text('Cancel'),
            ),
            FilledButton(
              onPressed: () => Navigator.pop(c, true),
              child: const Text('Save'),
            ),
          ],
        ),
      );
      if (save == true && mounted) {
        final date = DateTime.tryParse(controller.text);
        if (date == null)
          throw const FormatException('Enter a valid UTC timestamp');
        await phase3.setRetention(artifact.id, date);
        await load();
      }
    } catch (e) {
      if (mounted)
        ScaffoldMessenger.of(
          context,
        ).showSnackBar(SnackBar(content: Text('$e')));
    } finally {
      controller.dispose();
    }
  }
}
