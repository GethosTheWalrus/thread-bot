import 'package:flutter/material.dart';
import 'package:threadbot/models/autonomy.dart';
import 'package:threadbot/services/autonomy_api.dart';
import 'package:threadbot/widgets/agent_workspace_ui.dart';

class AgentToolsSheet extends StatefulWidget {
  final String agentId;
  final String agentName;
  final AutonomyApiService autonomy;
  final VoidCallback? onSaved;

  const AgentToolsSheet({
    super.key,
    required this.agentId,
    required this.agentName,
    required this.autonomy,
    this.onSaved,
  });

  static Future<void> show(
    BuildContext context, {
    required String agentId,
    required String agentName,
    required AutonomyApiService autonomy,
    VoidCallback? onSaved,
  }) => showModalBottomSheet<void>(
    context: context,
    isScrollControlled: true,
    backgroundColor: Colors.transparent,
    builder: (_) => AgentToolsSheet(
      agentId: agentId,
      agentName: agentName,
      autonomy: autonomy,
      onSaved: onSaved,
    ),
  );

  @override
  State<AgentToolsSheet> createState() => _AgentToolsSheetState();
}

class _AgentToolsSheetState extends State<AgentToolsSheet> {
  Draft? _draft;
  List<_AgentMcpServer> _servers = const [];
  bool _loading = true;
  bool _saving = false;
  String? _error;

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    try {
      final results = await Future.wait([
        widget.autonomy.draft(widget.agentId),
        widget.autonomy.mcpToolCatalog(),
      ]);
      final draft = results[0] as Draft;
      final data = results[1] as Map<String, dynamic>;
      final selected = draft.toolSelection.toSet();
      final servers = (data['servers'] as List? ?? const [])
          .whereType<Map>()
          .map((raw) {
            final server = Map<String, dynamic>.from(raw);
            final name = '${server['name'] ?? 'MCP server'}';
            final tools = (server['tools'] as List? ?? const [])
                .whereType<Map>()
                .map((rawTool) {
                  final tool = Map<String, dynamic>.from(rawTool);
                  final toolName = '${tool['name'] ?? ''}';
                  return _AgentMcpTool(
                    name: toolName,
                    description: '${tool['description'] ?? ''}',
                    identity: 'mcp:$name:$toolName',
                    selected:
                        selected.contains('mcp:$name:$toolName') ||
                        selected.contains('$name:$toolName'),
                  );
                })
                .where((tool) => tool.name.isNotEmpty)
                .toList();
            return _AgentMcpServer(name: name, tools: tools);
          })
          .where((server) => server.tools.isNotEmpty)
          .toList();
      if (!mounted) return;
      setState(() {
        _draft = draft;
        _servers = servers;
        _loading = false;
      });
    } catch (e) {
      if (!mounted) return;
      setState(() {
        _loading = false;
        _error = e.toString();
      });
    }
  }

  void _toggleServer(_AgentMcpServer server, bool selected) => setState(() {
    for (final tool in server.tools) tool.selected = selected;
  });

  Future<void> _save() async {
    final draft = _draft;
    if (draft == null) return;
    setState(() => _saving = true);
    try {
      final preserved = draft.toolSelection.where((identity) {
        if (identity.startsWith('mcp:')) return false;
        return !_servers.any(
          (server) => identity.startsWith('${server.name}:'),
        );
      }).toList();
      final selectedMcp = _servers
          .expand((server) => server.tools)
          .where((tool) => tool.selected)
          .map((tool) => tool.identity);
      await widget.autonomy.saveDraft(widget.agentId, {
        'optimistic_lock_version': draft.optimisticLockVersion,
        'schema_version': draft.schemaVersion,
        'config': draft.config,
        'prompt_template': draft.promptTemplate,
        'tool_selection': [...preserved, ...selectedMcp],
        'skill_selection': draft.skillSelection,
        'credential_bindings': draft.credentialBindings,
      });
      await widget.autonomy.activate(widget.agentId);
      widget.onSaved?.call();
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text('${widget.agentName} tools activated')),
      );
      Navigator.pop(context);
    } catch (e) {
      if (!mounted) return;
      setState(() => _saving = false);
      ScaffoldMessenger.of(
        context,
      ).showSnackBar(SnackBar(content: Text('Could not save Agent tools: $e')));
    }
  }

  @override
  Widget build(BuildContext context) {
    final height = MediaQuery.sizeOf(context).height * .82;
    return SafeArea(
      child: Center(
        child: ConstrainedBox(
          constraints: const BoxConstraints(maxWidth: 760),
          child: Material(
            color: agentSurface,
            borderRadius: const BorderRadius.vertical(top: Radius.circular(22)),
            child: SizedBox(
              height: height,
              child: Column(
                children: [
                  Padding(
                    padding: const EdgeInsets.fromLTRB(20, 16, 12, 10),
                    child: Row(
                      children: [
                        Expanded(
                          child: AgentIdentity(
                            name: widget.agentName,
                            radius: 18,
                          ),
                        ),
                        IconButton(
                          tooltip: 'Close',
                          onPressed: _saving
                              ? null
                              : () => Navigator.pop(context),
                          icon: const Icon(Icons.close),
                        ),
                      ],
                    ),
                  ),
                  const Padding(
                    padding: EdgeInsets.fromLTRB(20, 0, 20, 14),
                    child: Align(
                      alignment: Alignment.centerLeft,
                      child: Text(
                        'MCP capabilities',
                        style: TextStyle(
                          color: Color(0xFFA78BFA),
                          fontSize: 12,
                          fontWeight: FontWeight.w700,
                        ),
                      ),
                    ),
                  ),
                  const Padding(
                    padding: EdgeInsets.fromLTRB(20, 0, 20, 14),
                    child: Text(
                      'Choose which MCP tools this agent may use. Saving creates and activates a new immutable version.',
                      style: TextStyle(color: Colors.white54, height: 1.4),
                    ),
                  ),
                  const Divider(height: 1),
                  Expanded(
                    child: _loading
                        ? const Center(child: CircularProgressIndicator())
                        : _error != null
                        ? Center(
                            child: Padding(
                              padding: const EdgeInsets.all(24),
                              child: Column(
                                mainAxisSize: MainAxisSize.min,
                                children: [
                                  Text(_error!, textAlign: TextAlign.center),
                                  const SizedBox(height: 12),
                                  OutlinedButton(
                                    onPressed: _load,
                                    child: const Text('Retry'),
                                  ),
                                ],
                              ),
                            ),
                          )
                        : ListView.builder(
                            padding: const EdgeInsets.fromLTRB(16, 12, 16, 24),
                            itemCount: _servers.length,
                            itemBuilder: (context, index) {
                              final server = _servers[index];
                              final selectedCount = server.tools
                                  .where((tool) => tool.selected)
                                  .length;
                              return Card(
                                color: agentSurfaceRaised,
                                margin: const EdgeInsets.only(bottom: 10),
                                shape: RoundedRectangleBorder(
                                  borderRadius: BorderRadius.circular(12),
                                  side: const BorderSide(color: agentBorder),
                                ),
                                child: ExpansionTile(
                                  title: Text(server.name),
                                  subtitle: Text(
                                    '$selectedCount of ${server.tools.length} selected',
                                  ),
                                  leading: Checkbox(
                                    tristate: true,
                                    value: selectedCount == 0
                                        ? false
                                        : selectedCount == server.tools.length
                                        ? true
                                        : null,
                                    onChanged: _saving
                                        ? null
                                        : (value) => _toggleServer(
                                            server,
                                            value ?? true,
                                          ),
                                  ),
                                  children: server.tools
                                      .map(
                                        (tool) => CheckboxListTile(
                                          value: tool.selected,
                                          onChanged: _saving
                                              ? null
                                              : (value) => setState(
                                                  () => tool.selected =
                                                      value ?? false,
                                                ),
                                          title: Text(tool.name),
                                          subtitle: tool.description.isEmpty
                                              ? null
                                              : Text(
                                                  tool.description,
                                                  maxLines: 3,
                                                  overflow:
                                                      TextOverflow.ellipsis,
                                                ),
                                          controlAffinity:
                                              ListTileControlAffinity.leading,
                                        ),
                                      )
                                      .toList(),
                                ),
                              );
                            },
                          ),
                  ),
                  Padding(
                    padding: const EdgeInsets.fromLTRB(16, 10, 16, 16),
                    child: SizedBox(
                      width: double.infinity,
                      child: FilledButton.icon(
                        onPressed: _loading || _saving || _error != null
                            ? null
                            : _save,
                        icon: _saving
                            ? const SizedBox(
                                width: 16,
                                height: 16,
                                child: CircularProgressIndicator(
                                  strokeWidth: 2,
                                ),
                              )
                            : const Icon(Icons.verified_outlined),
                        label: Text(
                          _saving ? 'Activating…' : 'Save and activate',
                        ),
                      ),
                    ),
                  ),
                ],
              ),
            ),
          ),
        ),
      ),
    );
  }
}

class _AgentMcpServer {
  final String name;
  final List<_AgentMcpTool> tools;
  const _AgentMcpServer({required this.name, required this.tools});
}

class _AgentMcpTool {
  final String name, description, identity;
  bool selected;
  _AgentMcpTool({
    required this.name,
    required this.description,
    required this.identity,
    required this.selected,
  });
}
