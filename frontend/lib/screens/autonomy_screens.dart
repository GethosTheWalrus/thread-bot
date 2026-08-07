import 'dart:async';
import 'dart:convert';
import 'package:flutter/material.dart';
import 'package:flutter_markdown/flutter_markdown.dart';
import 'package:threadbot/models/autonomy.dart';
import 'package:threadbot/services/autonomy_api.dart';
import 'package:threadbot/services/autonomy_socket.dart';
import 'package:threadbot/services/phase2_api.dart';
import 'package:threadbot/models/phase2.dart';
import 'package:threadbot/models/phase3.dart';
import 'package:threadbot/services/phase3_api.dart';
import 'package:threadbot/services/phase4_api.dart';
import 'package:threadbot/models/phase4.dart';
import 'package:threadbot/widgets/phase4_panels.dart';
import 'package:threadbot/widgets/agent_workspace_ui.dart';
import 'package:threadbot/widgets/agent_tools_sheet.dart';
import 'package:threadbot/widgets/heartbeat_config_sheet.dart';
import 'package:url_launcher/url_launcher.dart';

class NewAgentScreen extends StatefulWidget {
  final AutonomyApiService api;
  const NewAgentScreen({super.key, required this.api});
  @override
  State<NewAgentScreen> createState() => _NewAgentState();
}

class _NewAgentState extends State<NewAgentScreen> {
  final name = TextEditingController(), description = TextEditingController();
  String? template;
  bool saving = false;
  List<Map<String, dynamic>> templates = const [];
  @override
  void initState() {
    super.initState();
    widget.api
        .templates()
        .then((value) {
          if (mounted) setState(() => templates = value);
        })
        .catchError((_) {});
  }

  @override
  void dispose() {
    name.dispose();
    description.dispose();
    super.dispose();
  }

  Future<void> create() async {
    if (name.text.trim().isEmpty) return;
    setState(() => saving = true);
    try {
      final agent = await widget.api.createAgent({
        'name': name.text.trim(),
        'description': description.text.trim().isEmpty
            ? null
            : description.text.trim(),
        'execution_mode': 'act',
        if (template != null) 'template_id': template,
        'concurrency_limit': 1,
        'queue_limit': 100,
      });
      if (mounted)
        Navigator.pushReplacementNamed(context, '/agents/${agent.id}');
    } catch (e) {
      if (mounted)
        ScaffoldMessenger.of(
          context,
        ).showSnackBar(SnackBar(content: Text('$e')));
    } finally {
      if (mounted) setState(() => saving = false);
    }
  }

  @override
  Widget build(BuildContext c) => Scaffold(
    body: SafeArea(
      child: Center(
        child: ConstrainedBox(
          constraints: const BoxConstraints(maxWidth: 760),
          child: ListView(
            padding: const EdgeInsets.fromLTRB(24, 20, 24, 48),
            children: [
              const AgentBreadcrumb(current: 'New agent'),
              const SizedBox(height: 18),
              const AgentPageHeader(
                eyebrow: 'Agent workspace',
                title: 'Create an agent',
                description:
                    'Agents belong to a Thread. Give this one a clear purpose, then configure its operating limits.',
              ),
              section(
                'Identity',
                Column(
                  children: [
                    TextField(
                      controller: name,
                      decoration: const InputDecoration(labelText: 'Name'),
                    ),
                    const SizedBox(height: 12),
                    TextField(
                      controller: description,
                      maxLines: 3,
                      decoration: const InputDecoration(
                        labelText: 'Description',
                      ),
                    ),
                  ],
                ),
              ),
              section(
                'Template',
                DropdownButtonFormField<String>(
                  initialValue: template,
                  items: [
                    const DropdownMenuItem(
                      value: null,
                      child: Text('Start from scratch'),
                    ),
                    ...templates.map(
                      (t) => DropdownMenuItem(
                        value: t['id']?.toString(),
                        child: Text(t['name']?.toString() ?? 'Template'),
                      ),
                    ),
                  ],
                  onChanged: (v) => setState(() => template = v),
                  decoration: const InputDecoration(labelText: 'Template'),
                ),
              ),
              FilledButton.icon(
                onPressed: saving ? null : create,
                icon: const Icon(Icons.add),
                label: Text(saving ? 'Creating…' : 'Create agent'),
              ),
            ],
          ),
        ),
      ),
    ),
  );
}

class AgentsScreen extends StatefulWidget {
  final AutonomyApiService api;
  const AgentsScreen({super.key, required this.api});
  @override
  State<AgentsScreen> createState() => _AgentsState();
}

class _AgentsState extends State<AgentsScreen> {
  late Future<CursorPage<Agent>> future;
  final search = TextEditingController();
  final List<Agent> all = [];
  String? nextCursor;
  bool loadingMore = false;
  @override
  void initState() {
    super.initState();
    future = widget.api.agents().then((page) {
      if (mounted)
        setState(() {
          all.addAll(page.items);
          nextCursor = page.nextCursor;
        });
      return page;
    });
  }

  Future<void> loadMore() async {
    if (loadingMore || nextCursor == null) return;
    setState(() => loadingMore = true);
    try {
      final page = await widget.api.agents(cursor: nextCursor);
      if (mounted)
        setState(() {
          all.addAll(page.items);
          nextCursor = page.nextCursor;
        });
    } finally {
      if (mounted) setState(() => loadingMore = false);
    }
  }

  @override
  void dispose() {
    search.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext c) => Scaffold(
    appBar: AppBar(
      title: const Text('Agents'),
      actions: [
        IconButton(
          onPressed: () => Navigator.pushNamed(c, '/agents/new'),
          icon: const Icon(Icons.add),
        ),
      ],
    ),
    body: FutureBuilder<CursorPage<Agent>>(
      future: future,
      builder: (c, s) {
        if (s.hasError &&
            s.error is ApiException &&
            (s.error as ApiException).unauthorized)
          return const Center(child: Text('Authentication required'));
        if (!s.hasData)
          return Center(
            child: s.hasError
                ? Text('${s.error}')
                : const CircularProgressIndicator(),
          );
        final a = all.isEmpty ? s.data!.items : all;
        return NotificationListener<ScrollNotification>(
          onNotification: (n) {
            if (n.metrics.extentAfter < 300) loadMore();
            return false;
          },
          child: ListView(
            padding: const EdgeInsets.all(16),
            children: [
              TextField(
                controller: search,
                decoration: const InputDecoration(
                  prefixIcon: Icon(Icons.search),
                  hintText: 'Search agents',
                ),
              ),
              const SizedBox(height: 12),
              for (final item in a.where(
                (x) => x.name.toLowerCase().contains(search.text.toLowerCase()),
              ))
                Card(
                  child: ListTile(
                    onTap: () => Navigator.pushNamed(c, '/agents/${item.id}'),
                    title: Text(item.name),
                    subtitle: Text('${item.status}\n${item.description ?? ''}'),
                    isThreeLine: true,
                  ),
                ),
            ],
          ),
        );
      },
    ),
  );
}

class AgentEditorScreen extends StatefulWidget {
  final String id;
  final AutonomyApiService api;
  const AgentEditorScreen({super.key, required this.id, required this.api});
  @override
  State<AgentEditorScreen> createState() => _EditorState();
}

class _EditorState extends State<AgentEditorScreen> {
  Agent? agent;
  Draft? draft;
  List<Version> versions = [];
  List<Trigger> triggers = [];
  List<Run> runs = [];
  final prompt = TextEditingController();
  String? error;
  bool saving = false, activating = false;
  @override
  void dispose() {
    prompt.dispose();
    super.dispose();
  }

  @override
  void initState() {
    super.initState();
    load();
  }

  Future<void> load() async {
    try {
      final a = await widget.api.agent(widget.id);
      Draft? d;
      try {
        d = await widget.api.draft(widget.id);
      } on ApiException catch (error) {
        if (error.status == 404) {
          d = Draft(agentId: widget.id);
        }
      }
      if (mounted)
        setState(() {
          agent = a;
          draft = d;
          prompt.text = d?.promptTemplate ?? '';
        });
      try {
        versions = await widget.api.versions(widget.id);
      } catch (_) {}
      try {
        triggers = await widget.api.triggers(widget.id);
      } catch (_) {}
      try {
        final page = await widget.api.runs(widget.id);
        runs = page.items;
      } catch (_) {}
      if (mounted) setState(() {});
    } catch (e) {
      if (mounted) setState(() => error = '$e');
    }
  }

  Future<void> save() async {
    if (draft == null) return;
    setState(() => saving = true);
    try {
      final config = Map<String, dynamic>.from(draft!.config);
      final d = await widget.api.saveDraft(widget.id, {
        'optimistic_lock_version': draft!.optimisticLockVersion,
        'schema_version': draft!.schemaVersion,
        'config': config,
        'prompt_template': prompt.text,
        'tool_selection': draft!.toolSelection,
        'skill_selection': draft!.skillSelection,
        'credential_bindings': draft!.credentialBindings,
      });
      if (mounted) setState(() => draft = d);
      if (mounted)
        ScaffoldMessenger.of(
          context,
        ).showSnackBar(const SnackBar(content: Text('Draft saved')));
    } catch (e) {
      if (mounted)
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(
            content: Text(
              e is ApiException && e.conflict
                  ? 'Draft conflict; reload before saving.'
                  : '$e',
            ),
          ),
        );
    } finally {
      if (mounted) setState(() => saving = false);
    }
  }

  Future<void> activateAgent() async {
    if (draft == null) return;
    setState(() => activating = true);
    try {
      await widget.api.activate(widget.id);
      await load();
      if (mounted)
        ScaffoldMessenger.of(
          context,
        ).showSnackBar(const SnackBar(content: Text('Agent activated')));
    } catch (e) {
      if (mounted)
        ScaffoldMessenger.of(
          context,
        ).showSnackBar(SnackBar(content: Text('$e')));
    } finally {
      if (mounted) setState(() => activating = false);
    }
  }

  Future<void> toggleLifecycle() async {
    if (agent == null) return;
    try {
      await widget.api.lifecycle(agent!.id, agent!.status != 'active');
      await load();
    } catch (e) {
      if (mounted)
        ScaffoldMessenger.of(
          context,
        ).showSnackBar(SnackBar(content: Text('$e')));
    }
  }

  Future<void> addSchedule() async {
    final cron = TextEditingController(text: '0 * * * *'),
        timezone = TextEditingController(text: 'UTC');
    String overlap = 'skip';
    try {
      await showDialog(
        context: context,
        builder: (dialogContext) => AlertDialog(
          title: const Text('Schedule trigger'),
          content: StatefulBuilder(
            builder: (_, setLocal) => Column(
              mainAxisSize: MainAxisSize.min,
              children: [
                TextField(
                  controller: cron,
                  decoration: const InputDecoration(
                    labelText: 'Five-field cron',
                  ),
                ),
                TextField(
                  controller: timezone,
                  decoration: const InputDecoration(labelText: 'Timezone'),
                ),
                DropdownButtonFormField<String>(
                  initialValue: overlap,
                  items: const [
                    DropdownMenuItem(
                      value: 'skip',
                      child: Text('Skip overlap'),
                    ),
                    DropdownMenuItem(
                      value: 'buffer_one',
                      child: Text('Buffer one'),
                    ),
                  ],
                  onChanged: (v) {
                    if (v != null) setLocal(() => overlap = v);
                  },
                ),
              ],
            ),
          ),
          actions: [
            TextButton(
              onPressed: () => Navigator.pop(dialogContext),
              child: const Text('Cancel'),
            ),
            FilledButton(
              onPressed: () async {
                try {
                  final preview = await widget.api.previewSchedule(
                    cron.text,
                    timezone.text,
                  );
                  if (!mounted) return;
                  final trigger = await widget.api.createTrigger(widget.id, {
                    'trigger_type': 'schedule',
                    'config': {
                      'cron': cron.text,
                      'timezone': timezone.text,
                      'overlap': overlap,
                    },
                    'is_active': true,
                  });
                  await widget.api.registerTriggerSchedule(trigger.id);
                  if (!dialogContext.mounted) return;
                  if (mounted) {
                    Navigator.pop(dialogContext);
                    await load();
                    if (!mounted) return;
                    ScaffoldMessenger.of(context).showSnackBar(
                      SnackBar(
                        content: Text(
                          '${(preview['occurrences'] as List?)?.length ?? 0} occurrences previewed',
                        ),
                      ),
                    );
                  }
                } catch (e) {
                  if (mounted)
                    ScaffoldMessenger.of(
                      context,
                    ).showSnackBar(SnackBar(content: Text('$e')));
                }
              },
              child: const Text('Save'),
            ),
          ],
        ),
      );
    } finally {
      cron.dispose();
      timezone.dispose();
    }
  }

  Future<void> startRun({required bool dryRun}) async {
    final message = TextEditingController();
    try {
      final confirmed = await showDialog<bool>(
        context: context,
        builder: (dialogContext) => AlertDialog(
          title: Text(dryRun ? 'Dry run' : 'Run agent now'),
          content: TextField(
            controller: message,
            autofocus: true,
            minLines: 3,
            maxLines: 8,
            decoration: const InputDecoration(
              labelText: 'Goal or trigger context',
            ),
          ),
          actions: [
            TextButton(
              onPressed: () => Navigator.pop(dialogContext, false),
              child: const Text('Cancel'),
            ),
            FilledButton(
              onPressed: () => Navigator.pop(dialogContext, true),
              child: Text(dryRun ? 'Preview' : 'Run'),
            ),
          ],
        ),
      );
      if (confirmed != true || message.text.trim().isEmpty || !mounted) return;
      final run = await widget.api.run(
        widget.id,
        message.text.trim(),
        dryRun: dryRun,
        idempotencyKey: AutonomyApiService.newIdempotencyKey(),
      );
      await load();
      if (mounted) Navigator.pushNamed(context, '/agent-runs/${run.id}');
    } catch (e) {
      if (mounted) {
        ScaffoldMessenger.of(
          context,
        ).showSnackBar(SnackBar(content: Text('$e')));
      }
    } finally {
      message.dispose();
    }
  }

  Future<void> setSchedulePaused(Trigger trigger, bool paused) async {
    try {
      if (paused) {
        await widget.api.pauseTriggerSchedule(trigger.id);
      } else {
        await widget.api.resumeTriggerSchedule(trigger.id);
      }
      await load();
    } catch (e) {
      if (mounted) {
        ScaffoldMessenger.of(
          context,
        ).showSnackBar(SnackBar(content: Text('$e')));
      }
    }
  }

  Future<void> manageTools() => AgentToolsSheet.show(
    context,
    agentId: agent!.id,
    agentName: agent!.name,
    autonomy: widget.api,
    onSaved: load,
  );

  String capabilityLabel(String identity) {
    if (identity.startsWith('mcp:')) {
      final parts = identity.split(':');
      if (parts.length >= 3)
        return '${parts[1]} / ${parts.sublist(2).join(':')}';
    }
    if (identity.startsWith('builtin:')) return identity.substring(8);
    return identity;
  }

  Widget capabilityGroup({
    required IconData icon,
    required String title,
    required String emptyText,
    required List<String> values,
  }) => Container(
    width: double.infinity,
    padding: const EdgeInsets.all(14),
    decoration: BoxDecoration(
      color: agentSurfaceRaised,
      borderRadius: BorderRadius.circular(12),
      border: Border.all(color: agentBorder),
    ),
    child: Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Row(
          children: [
            Icon(icon, size: 18, color: const Color(0xFFA78BFA)),
            const SizedBox(width: 8),
            Text(title, style: const TextStyle(fontWeight: FontWeight.w700)),
            const Spacer(),
            Text(
              '${values.length}',
              style: const TextStyle(color: Colors.white54),
            ),
          ],
        ),
        const SizedBox(height: 10),
        if (values.isEmpty)
          Text(emptyText, style: const TextStyle(color: Colors.white54))
        else
          Wrap(
            spacing: 7,
            runSpacing: 7,
            children: [
              for (final value in values)
                Chip(
                  visualDensity: VisualDensity.compact,
                  label: Text(capabilityLabel(value)),
                ),
            ],
          ),
      ],
    ),
  );

  Widget capabilitiesSection() {
    final selection = draft?.toolSelection ?? const <String>[];
    final mcp = selection.where((item) => item.startsWith('mcp:')).toList();
    final builtins = selection
        .where((item) => item.startsWith('builtin:'))
        .toList();
    final other = selection
        .where(
          (item) => !item.startsWith('mcp:') && !item.startsWith('builtin:'),
        )
        .toList();
    final selectedSkills = draft?.skillSelection ?? const <String>[];
    return AgentSection(
      title: 'Capabilities',
      description:
          'These are the tools and skills in the next immutable Agent version.',
      trailing: OutlinedButton.icon(
        onPressed: draft == null ? null : manageTools,
        icon: const Icon(Icons.tune, size: 18),
        label: const Text('Manage MCP tools'),
      ),
      child: Column(
        children: [
          capabilityGroup(
            icon: Icons.hub_outlined,
            title: 'MCP tools',
            emptyText:
                'No MCP tools selected. This Agent cannot query external MCP servers.',
            values: mcp,
          ),
          const SizedBox(height: 10),
          capabilityGroup(
            icon: Icons.extension_outlined,
            title: 'Built-in and other tools',
            emptyText: 'No built-in tools selected.',
            values: [...builtins, ...other],
          ),
          const SizedBox(height: 10),
          capabilityGroup(
            icon: Icons.auto_stories_outlined,
            title: 'Skills',
            emptyText: 'No skills selected.',
            values: selectedSkills,
          ),
          if ((draft?.credentialBindings.length ?? 0) > 0) ...[
            const SizedBox(height: 10),
            Align(
              alignment: Alignment.centerLeft,
              child: Text(
                '${draft!.credentialBindings.length} credential binding(s) configured',
                style: const TextStyle(color: Colors.white60),
              ),
            ),
          ],
        ],
      ),
    );
  }

  Widget automationSection() => AgentSection(
    title: 'Automation',
    description: 'Choose when this Agent may start work without a new message.',
    trailing: Wrap(
      spacing: 8,
      children: [
        OutlinedButton.icon(
          onPressed: () => HeartbeatConfigSheet.show(
            context,
            agentId: agent!.id,
            agentName: agent!.name,
            api: widget.api,
          ),
          icon: const Icon(Icons.favorite_border, size: 18),
          label: const Text('Heartbeat'),
        ),
        OutlinedButton.icon(
          onPressed: addSchedule,
          icon: const Icon(Icons.add_alarm_outlined, size: 18),
          label: const Text('Add schedule'),
        ),
      ],
    ),
    child: Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        if (triggers.where((item) => item.type == 'schedule').isEmpty)
          const Text(
            'No schedules configured. Heartbeat settings are managed separately.',
            style: TextStyle(color: Colors.white54),
          ),
        for (final trigger in triggers.where((x) => x.type == 'schedule'))
          Container(
            margin: const EdgeInsets.only(bottom: 8),
            padding: const EdgeInsets.fromLTRB(14, 8, 8, 8),
            decoration: BoxDecoration(
              color: agentSurfaceRaised,
              borderRadius: BorderRadius.circular(12),
              border: Border.all(color: agentBorder),
            ),
            child: Row(
              children: [
                const Icon(Icons.schedule, size: 18, color: Colors.white60),
                const SizedBox(width: 10),
                Expanded(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text(trigger.config['cron']?.toString() ?? 'Schedule'),
                      Text(
                        trigger.config['timezone']?.toString() ?? 'UTC',
                        style: const TextStyle(
                          color: Colors.white54,
                          fontSize: 12,
                        ),
                      ),
                    ],
                  ),
                ),
                PopupMenuButton<bool>(
                  tooltip: 'Schedule actions',
                  onSelected: (paused) => setSchedulePaused(trigger, paused),
                  itemBuilder: (_) => const [
                    PopupMenuItem(value: true, child: Text('Pause schedule')),
                    PopupMenuItem(value: false, child: Text('Resume schedule')),
                  ],
                ),
              ],
            ),
          ),
      ],
    ),
  );

  @override
  Widget build(BuildContext c) {
    if (error != null) return Scaffold(body: Center(child: Text(error!)));
    if (agent == null)
      return const Scaffold(body: Center(child: CircularProgressIndicator()));
    return Scaffold(
      body: Center(
        child: ConstrainedBox(
          constraints: const BoxConstraints(maxWidth: 900),
          child: ListView(
            padding: const EdgeInsets.fromLTRB(20, 20, 20, 40),
            children: [
              AgentBreadcrumb(
                current: agent!.name,
                onBack: () {
                  if (Navigator.canPop(context)) {
                    Navigator.pop(context);
                  } else {
                    Navigator.pushReplacementNamed(
                      context,
                      '/agent-details/${agent!.id}',
                    );
                  }
                },
              ),
              const SizedBox(height: 16),
              AgentPageHeader(
                eyebrow: 'Agent settings',
                title: agent!.name,
                description: agent!.threadTitle?.isNotEmpty == true
                    ? 'Configured for ${agent!.threadTitle}'
                    : 'Configure what this Agent does and when it works.',
                action: AgentStatusPill(agent!.status),
              ),
              AgentSection(
                title: 'Status and actions',
                description: agent!.activeVersionId == null
                    ? 'This Agent has no active version yet. Save its instructions, then activate it.'
                    : 'Changes remain a draft until you activate a new immutable version.',
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Wrap(
                      spacing: 10,
                      runSpacing: 10,
                      children: [
                        AgentMetric(
                          label: 'Status',
                          value: agent!.status,
                          icon: agent!.status == 'active'
                              ? Icons.check_circle_outline
                              : Icons.pause_circle_outline,
                        ),
                        AgentMetric(
                          label: 'Active version',
                          value: agent!.activeVersionId == null
                              ? 'Not activated'
                              : versions
                                        .where(
                                          (item) =>
                                              item.id == agent!.activeVersionId,
                                        )
                                        .map(
                                          (item) => 'Version ${item.version}',
                                        )
                                        .firstOrNull ??
                                    'Active',
                          icon: Icons.layers_outlined,
                        ),
                        AgentMetric(
                          label: 'Thread role',
                          value: agent!.isModerator
                              ? 'Moderator'
                              : 'Participant',
                          icon: agent!.isModerator
                              ? Icons.shield_outlined
                              : Icons.person_outline,
                        ),
                      ],
                    ),
                    const SizedBox(height: 14),
                    Wrap(
                      spacing: 10,
                      runSpacing: 10,
                      children: [
                        OutlinedButton.icon(
                          onPressed: agent!.threadId.isEmpty
                              ? null
                              : () => Navigator.pushNamed(
                                  context,
                                  '/thread/${agent!.threadId}',
                                ),
                          icon: const Icon(Icons.forum_outlined),
                          label: const Text('Open Thread'),
                        ),
                        OutlinedButton.icon(
                          onPressed: saving ? null : save,
                          icon: const Icon(Icons.save_outlined),
                          label: Text(saving ? 'Saving…' : 'Save draft'),
                        ),
                        FilledButton.icon(
                          onPressed: activating || draft == null
                              ? null
                              : activateAgent,
                          icon: const Icon(Icons.rocket_launch_outlined),
                          label: Text(
                            activating ? 'Activating…' : 'Activate changes',
                          ),
                        ),
                        OutlinedButton.icon(
                          onPressed: toggleLifecycle,
                          icon: Icon(
                            agent!.status == 'active'
                                ? Icons.pause
                                : Icons.play_arrow,
                          ),
                          label: Text(
                            agent!.status == 'active'
                                ? 'Pause Agent'
                                : 'Resume Agent',
                          ),
                        ),
                      ],
                    ),
                  ],
                ),
              ),
              AgentSection(
                title: 'Instructions',
                description:
                    'The standing mandate used for messages and automatic heartbeat work.',
                child: TextField(
                  controller: prompt,
                  minLines: 8,
                  maxLines: 16,
                  decoration: const InputDecoration(
                    hintText:
                        'What should this agent do, prioritize, and avoid?',
                  ),
                ),
              ),
              capabilitiesSection(),
              automationSection(),
              AgentSection(
                title: 'Recent runs',
                description:
                    'Start work now or inspect the latest Agent activity.',
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Wrap(
                      spacing: 8,
                      children: [
                        FilledButton.icon(
                          onPressed: agent!.activeVersionId == null
                              ? null
                              : () => startRun(dryRun: false),
                          icon: const Icon(Icons.play_arrow),
                          label: const Text('Run now'),
                        ),
                        OutlinedButton.icon(
                          onPressed: agent!.activeVersionId == null
                              ? null
                              : () => startRun(dryRun: true),
                          icon: const Icon(Icons.science_outlined),
                          label: const Text('Dry run'),
                        ),
                      ],
                    ),
                    const SizedBox(height: 8),
                    for (final run in runs.take(5))
                      ListTile(
                        contentPadding: EdgeInsets.zero,
                        leading: AgentStatusPill(run.status),
                        title: Text(
                          run.route == 'heartbeat'
                              ? 'Heartbeat run'
                              : 'Agent run',
                        ),
                        subtitle: Text(
                          run.queuedAt == null
                              ? run.mode
                              : '${run.mode} • ${run.queuedAt!.toLocal()}',
                          maxLines: 1,
                          overflow: TextOverflow.ellipsis,
                        ),
                        trailing: const Icon(Icons.chevron_right),
                        onTap: () =>
                            Navigator.pushNamed(c, '/agent-runs/${run.id}'),
                      ),
                    if (runs.isEmpty)
                      const Padding(
                        padding: EdgeInsets.only(top: 8),
                        child: Text(
                          'No runs yet.',
                          style: TextStyle(color: Colors.white54),
                        ),
                      ),
                  ],
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }
}

Widget section(String title, Widget child) =>
    AgentSection(title: title, child: child);

class RunScreen extends StatefulWidget {
  final String id;
  final AutonomyApiService api;
  const RunScreen({super.key, required this.id, required this.api});
  @override
  State<RunScreen> createState() => _RunState();
}

class _RunState extends State<RunScreen> {
  Run? run;
  List<RunEvent> events = [];
  AutonomySocket<RunEvent>? socket;
  StreamSubscription<RunEvent>? subscription;
  List<Approval> approvals = const [];
  Map<String, dynamic> stateDiff = const {};
  List<AgentHandoff> handoffs = const [];
  List<Artifact> artifacts = const [];
  Map<String, SlaStatus> slaStatuses = {};
  bool loading = true;
  String? error;
  late final Phase4ApiService phase4 = Phase4ApiService(widget.api);
  @override
  void initState() {
    super.initState();
    load();
    socket = AutonomySocket<RunEvent>(
      uriBuilder: (after) => widget.api.websocketUri(
        '/api/autonomy/runs/${widget.id}/events/ws',
        query: {'after': '$after'},
      ),
      decode: RunEvent.fromJson,
      onGap: _refetchAfter,
      strictSequence: true,
    );
    subscription = socket!.stream.listen((event) {
      if (!mounted) return;
      setState(() {
        if (!events.any((x) => x.sequence == event.sequence)) {
          events = [...events, event]
            ..sort((a, b) => a.sequence.compareTo(b.sequence));
        }
      });
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
      final r = await widget.api.runDetail(widget.id);
      final e = await widget.api.events(widget.id);
      List<Approval> a = const [];
      try {
        a = (await Phase2ApiService(
          widget.api,
        ).approvals()).where((item) => item.runId == widget.id).toList();
      } catch (_) {}
      try {
        stateDiff = await Phase2ApiService(widget.api).stateDiff(widget.id);
      } catch (_) {}
      try {
        handoffs = (await Phase3ApiService(
          widget.api,
        ).handoffs()).items.where((x) => x.sourceRunId == widget.id).toList();
        final phase3 = Phase3ApiService(widget.api);
        final statuses = await Future.wait(
          handoffs.map((x) => phase3.sla(x.id)),
        );
        slaStatuses = {for (final status in statuses) status.handoffId: status};
      } catch (_) {}
      try {
        artifacts = (await Phase3ApiService(
          widget.api,
        ).artifacts(runId: widget.id)).items;
      } catch (_) {}
      if (mounted)
        setState(() {
          run = r;
          events = e.items;
          approvals = a;
          loading = false;
        });
    } catch (e) {
      if (mounted)
        setState(() {
          error = '$e';
          loading = false;
        });
    }
  }

  Future<int> _refetchAfter(int after) async {
    final page = await widget.api.events(widget.id, after: after);
    if (mounted)
      setState(() {
        for (final item in page.items) {
          if (!events.any((x) => x.sequence == item.sequence)) events.add(item);
        }
        events.sort((a, b) => a.sequence.compareTo(b.sequence));
      });
    return int.tryParse(page.nextCursor ?? '') ??
        (page.items.isEmpty ? after : page.items.last.sequence);
  }

  Future<void> _cancel() async {
    try {
      await widget.api.cancel(widget.id);
      await load();
      if (mounted)
        ScaffoldMessenger.of(
          context,
        ).showSnackBar(const SnackBar(content: Text('Cancellation requested')));
    } catch (e) {
      if (mounted)
        ScaffoldMessenger.of(
          context,
        ).showSnackBar(SnackBar(content: Text('$e')));
    }
  }

  @override
  void dispose() {
    subscription?.cancel();
    socket?.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext c) => Scaffold(
    body: loading && run == null
        ? const Center(child: CircularProgressIndicator())
        : error != null && run == null
        ? Center(
            child: Column(
              mainAxisSize: MainAxisSize.min,
              children: [
                const Icon(
                  Icons.error_outline_rounded,
                  size: 40,
                  color: Colors.redAccent,
                ),
                const SizedBox(height: 12),
                Text(error!, textAlign: TextAlign.center),
                const SizedBox(height: 12),
                FilledButton.tonal(onPressed: load, child: const Text('Retry')),
              ],
            ),
          )
        : Center(
            child: ConstrainedBox(
              constraints: const BoxConstraints(maxWidth: 1040),
              child: ListView(
                padding: const EdgeInsets.fromLTRB(20, 20, 20, 40),
                children: [
                  AgentBreadcrumb(
                    current: run!.agentName ?? 'Agent run',
                    onBack: () {
                      if (Navigator.canPop(context)) {
                        Navigator.pop(context);
                      } else if (run!.agentId.isNotEmpty) {
                        Navigator.pushReplacementNamed(
                          context,
                          '/agent-details/${run!.agentId}',
                        );
                      } else {
                        Navigator.pushReplacementNamed(context, '/agents-list');
                      }
                    },
                  ),
                  const SizedBox(height: 16),
                  AgentPageHeader(
                    eyebrow: 'Run details',
                    title: run!.agentName ?? 'Agent run',
                    description: run!.agentHandle?.isNotEmpty == true
                        ? '@${run!.agentHandle} • inspect output, approvals, and activity'
                        : 'Inspect output, approvals, and activity.',
                    action: IconButton(
                      tooltip: 'Refresh run',
                      onPressed: loading ? null : load,
                      icon: const Icon(Icons.refresh_rounded),
                    ),
                  ),
                  Wrap(
                    spacing: 8,
                    runSpacing: 8,
                    children: [
                      AgentStatusPill(run!.status),
                      Chip(label: Text(run!.mode.replaceAll('_', ' '))),
                      if (run!.route.isNotEmpty)
                        Chip(label: Text(run!.route.replaceAll('_', ' '))),
                      if (run!.mode == 'dry_run')
                        const Chip(label: Text('DRY RUN')),
                      if (run!.status == 'queued' ||
                          run!.status == 'running' ||
                          run!.status == 'waiting_approval' ||
                          run!.status == 'waiting_handoff')
                        OutlinedButton(
                          onPressed: _cancel,
                          child: const Text('Cancel'),
                        ),
                    ],
                  ),
                  if (run!.outputSummary?.trim().isNotEmpty == true)
                    section(
                      'Output',
                      SelectionArea(
                        child: MarkdownBody(
                          data: run!.outputSummary!,
                          selectable: false,
                          softLineBreak: true,
                          styleSheet: _runMarkdownStyle(context),
                          onTapLink: (_, href, _) async {
                            final uri = href == null
                                ? null
                                : Uri.tryParse(href);
                            if (uri != null && await canLaunchUrl(uri)) {
                              await launchUrl(
                                uri,
                                mode: LaunchMode.externalApplication,
                              );
                            }
                          },
                        ),
                      ),
                    ),
                  if (approvals.isNotEmpty)
                    section(
                      'Approvals',
                      Column(
                        children: [
                          for (final approval in approvals)
                            ListTile(
                              title: Text(approval.actionId),
                              subtitle: Text(
                                '${approval.riskLevel} • ${approval.status}\nTarget: ${approval.target}\nArgs: ${approval.arguments}\nPolicy: ${approval.explanation}${approval.expiresAt == null ? '' : '\nExpires: ${approval.expiresAt!.toLocal()}'}',
                              ),
                              trailing: Wrap(
                                children: [
                                  TextButton(
                                    onPressed: approval.status == 'pending'
                                        ? () async {
                                            await Phase2ApiService(
                                              widget.api,
                                            ).decide(approval.id, 'denied');
                                            load();
                                          }
                                        : null,
                                    child: const Text('Deny'),
                                  ),
                                  FilledButton(
                                    onPressed: approval.status == 'pending'
                                        ? () async {
                                            await Phase2ApiService(
                                              widget.api,
                                            ).decide(approval.id, 'approved');
                                            load();
                                          }
                                        : null,
                                    child: const Text('Approve'),
                                  ),
                                ],
                              ),
                            ),
                        ],
                      ),
                    ),
                  section(
                    'State changes',
                    stateDiff['supported'] == false
                        ? const Text('No state changes recorded.')
                        : SelectableText(
                            const JsonEncoder.withIndent(
                              '  ',
                            ).convert(stateDiff['diff'] ?? stateDiff),
                          ),
                  ),
                  section(
                    'Handoff graph / SLA',
                    handoffs.isEmpty
                        ? const Text('No handoffs recorded for this run.')
                        : Column(
                            children: [
                              for (final handoff in handoffs)
                                ListTile(
                                  leading: const Icon(
                                    Icons.account_tree_outlined,
                                  ),
                                  title: Text(
                                    '${handoff.status} → ${handoff.targetAgentId}',
                                  ),
                                  subtitle: Text(
                                    'Contract ${handoff.contractId}\nAcknowledgement: ${handoff.acknowledgementDeadline ?? '—'}\nCompletion: ${handoff.completionDeadline ?? '—'}\nSLA: ${slaStatuses[handoff.id]?.workflowStatus ?? 'unknown'}',
                                  ),
                                ),
                            ],
                          ),
                  ),
                  section(
                    'Artifacts',
                    artifacts.isEmpty
                        ? const Text('No retained artifacts for this run.')
                        : Column(
                            children: [
                              for (final artifact in artifacts)
                                ListTile(
                                  leading: const Icon(
                                    Icons.description_outlined,
                                  ),
                                  title: Text(artifact.contentType),
                                  subtitle: Text(
                                    '${artifact.classification} • ${artifact.sizeBytes} bytes\nSHA-256 ${artifact.sha256}',
                                  ),
                                  trailing: artifact.onLegalHold
                                      ? const Chip(label: Text('Legal hold'))
                                      : null,
                                ),
                            ],
                          ),
                  ),
                  ReplayPanel(api: phase4, runId: widget.id),
                  section(
                    'Activity timeline',
                    events.isEmpty
                        ? const Text(
                            'No events recorded yet.',
                            style: TextStyle(color: Colors.white54),
                          )
                        : Column(
                            children: [
                              for (final e in events.reversed) _runEventTile(e),
                            ],
                          ),
                  ),
                ],
              ),
            ),
          ),
  );

  Widget _runEventTile(RunEvent event) {
    final safePayload = redactMap(event.payload);
    final summary = _eventSummary(safePayload);
    final details = const JsonEncoder.withIndent('  ').convert(safePayload);
    return Card(
      margin: const EdgeInsets.only(bottom: 8),
      color: const Color(0xFF191426),
      child: ExpansionTile(
        leading: CircleAvatar(
          radius: 16,
          backgroundColor: const Color(0xFF8B5CF6).withValues(alpha: 0.18),
          child: Text(
            '${event.sequence}',
            style: const TextStyle(fontSize: 10, color: Color(0xFFC4B5FD)),
          ),
        ),
        title: Text(
          event.type.replaceAll('_', ' '),
          style: const TextStyle(fontWeight: FontWeight.w600),
        ),
        subtitle: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            if (summary.isNotEmpty)
              Text(summary, maxLines: 2, overflow: TextOverflow.ellipsis),
            if (event.createdAt != null)
              Text(
                event.createdAt!.toLocal().toString(),
                style: const TextStyle(fontSize: 11, color: Colors.white38),
              ),
          ],
        ),
        childrenPadding: const EdgeInsets.fromLTRB(16, 0, 16, 14),
        children: [
          if (safePayload.isEmpty)
            const Align(
              alignment: Alignment.centerLeft,
              child: Text(
                'No event details.',
                style: TextStyle(color: Colors.white54),
              ),
            )
          else
            Align(
              alignment: Alignment.centerLeft,
              child: SelectableText(
                details,
                style: const TextStyle(
                  fontFamily: 'monospace',
                  fontSize: 12,
                  color: Colors.white70,
                ),
              ),
            ),
        ],
      ),
    );
  }

  String _eventSummary(Map<String, dynamic> payload) {
    for (final key in const [
      'display_content',
      'summary',
      'message',
      'reason',
      'error',
      'status',
      'decision',
    ]) {
      final value = payload[key];
      if (value is String && value.trim().isNotEmpty) return value.trim();
    }
    return '';
  }

  MarkdownStyleSheet _runMarkdownStyle(
    BuildContext context,
  ) => MarkdownStyleSheet(
    p: const TextStyle(fontSize: 15, height: 1.55, color: Color(0xFFE4E4E7)),
    h1: const TextStyle(
      fontSize: 24,
      height: 1.3,
      fontWeight: FontWeight.w700,
      color: Colors.white,
    ),
    h2: const TextStyle(
      fontSize: 20,
      height: 1.35,
      fontWeight: FontWeight.w700,
      color: Colors.white,
    ),
    h3: const TextStyle(
      fontSize: 17,
      height: 1.4,
      fontWeight: FontWeight.w700,
      color: Colors.white,
    ),
    strong: const TextStyle(fontWeight: FontWeight.w700, color: Colors.white),
    code: const TextStyle(
      fontFamily: 'monospace',
      color: Color(0xFFC4B5FD),
      backgroundColor: Color(0xFF211B35),
    ),
    codeblockDecoration: BoxDecoration(
      color: const Color(0xFF111118),
      borderRadius: BorderRadius.circular(8),
      border: Border.all(color: Colors.white.withValues(alpha: 0.06)),
    ),
    codeblockPadding: const EdgeInsets.all(16),
    blockquoteDecoration: const BoxDecoration(
      border: Border(left: BorderSide(color: Color(0xFF8B5CF6), width: 3)),
    ),
    blockquotePadding: const EdgeInsets.only(left: 12),
    listBullet: const TextStyle(color: Color(0xFF8B5CF6)),
    a: const TextStyle(
      color: Color(0xFFA78BFA),
      decoration: TextDecoration.underline,
    ),
  );
}

class AuditScreen extends StatefulWidget {
  final AutonomyApiService api;
  const AuditScreen({super.key, required this.api});
  @override
  State<AuditScreen> createState() => _AuditState();
}

class _AuditState extends State<AuditScreen> {
  late Future<CursorPage<AuditEntry>> future;
  final entries = <AuditEntry>[];
  String? nextCursor;
  bool loadingMore = false;
  @override
  void initState() {
    super.initState();
    future = widget.api.audit().then((page) {
      if (mounted)
        setState(() {
          entries.addAll(page.items);
          nextCursor = page.nextCursor;
        });
      return page;
    });
  }

  Future<void> loadMore() async {
    if (loadingMore || nextCursor == null) return;
    setState(() => loadingMore = true);
    try {
      final page = await widget.api.audit(cursor: nextCursor);
      if (mounted)
        setState(() {
          entries.addAll(page.items);
          nextCursor = page.nextCursor;
        });
    } finally {
      if (mounted) setState(() => loadingMore = false);
    }
  }

  @override
  Widget build(BuildContext c) => Scaffold(
    appBar: AppBar(title: const Text('Audit')),
    body: FutureBuilder<CursorPage<AuditEntry>>(
      future: future,
      builder: (c, s) {
        if (s.hasError &&
            s.error is ApiException &&
            (s.error as ApiException).unauthorized)
          return const Center(child: Text('Authentication required'));
        if (!s.hasData)
          return Center(
            child: s.hasError
                ? Text('${s.error}')
                : const CircularProgressIndicator(),
          );
        return NotificationListener<ScrollNotification>(
          onNotification: (n) {
            if (n.metrics.extentAfter < 300) loadMore();
            return false;
          },
          child: ListView(
            children: [
              for (final e in (entries.isEmpty ? s.data!.items : entries))
                ListTile(title: Text(e.type), subtitle: Text(e.resourceType)),
            ],
          ),
        );
      },
    ),
  );
}
