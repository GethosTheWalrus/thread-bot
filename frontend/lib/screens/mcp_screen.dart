import 'package:flutter/material.dart';
import 'package:threadbot/models/mcp_server.dart';
import 'package:threadbot/services/api_service.dart';
import 'package:url_launcher/url_launcher.dart';

class MCPScreen extends StatefulWidget {
  const MCPScreen({super.key});

  @override
  State<MCPScreen> createState() => _MCPScreenState();
}

class _MCPScreenState extends State<MCPScreen> {
  final ApiService _api = ApiService();
  List<MCPServer> _servers = [];
  bool _isLoading = true;
  String? _error;

  @override
  void initState() {
    super.initState();
    _loadServers();
  }

  Future<void> _loadServers() async {
    setState(() => _isLoading = true);
    try {
      final servers = await _api.getMCPServers();
      if (mounted) {
        setState(() {
          _servers = servers;
          _isLoading = false;
        });
      }
    } catch (e) {
      if (mounted) {
        setState(() {
          _error = e.toString();
          _isLoading = false;
        });
      }
    }
  }

  Future<void> _showServerDialog({MCPServer? server}) async {
    final nameController = TextEditingController(text: server?.name);
    final imageController = TextEditingController(text: server?.image);

    // Build initial key-value lists from existing server data
    final List<_KVEntry> envEntries = [];
    final List<_KVEntry> argEntries = [];

    if (server != null) {
      for (final e in server.envVars.entries) {
        envEntries.add(_KVEntry(
          key: TextEditingController(text: e.key),
          value: TextEditingController(text: e.value.toString()),
        ));
      }
      for (final e in server.args.entries) {
        argEntries.add(_KVEntry(
          key: TextEditingController(text: e.key),
          value: TextEditingController(text: e.value.toString()),
        ));
      }
    }

    showGeneralDialog(
      context: context,
      barrierDismissible: true,
      barrierLabel: 'Dismiss',
      transitionDuration: const Duration(milliseconds: 300),
      pageBuilder: (ctx, anim1, anim2) => _ServerDialogContent(
        nameController: nameController,
        imageController: imageController,
        envEntries: envEntries,
        argEntries: argEntries,
        isEdit: server != null,
        onSave: (env, args) async {
          try {
            if (server == null) {
              await _api.createMCPServer(
                name: nameController.text,
                image: imageController.text,
                envVars: env,
                args: args,
              );
            } else {
              await _api.updateMCPServer(
                server.id,
                nameController.text,
                imageController.text,
                env.map((k, v) => MapEntry(k, v.toString())),
                args: args.map((k, v) => MapEntry(k, v.toString())),
              );
            }
            Navigator.pop(ctx);
            _loadServers();
          } catch (e) {
            ScaffoldMessenger.of(context).showSnackBar(
                SnackBar(content: Text('Error: $e')));
          }
        },
        onCancel: () => Navigator.pop(ctx),
      ),
      transitionBuilder: (ctx, anim1, anim2, child) => FadeTransition(
        opacity: anim1,
        child: ScaleTransition(
          scale: anim1.drive(Tween(begin: 0.9, end: 1.0).chain(CurveTween(curve: Curves.easeOutCubic))),
          child: child,
        ),
      ),
    );
  }

  Future<void> _toggleServer(MCPServer server) async {
    try {
      await _api.toggleMCPServer(server.id);
      _loadServers();
    } catch (e) {
      ScaffoldMessenger.of(context)
          .showSnackBar(SnackBar(content: Text('Error: $e')));
    }
  }

  Future<void> _testServer(MCPServer server) async {
    ScaffoldMessenger.of(context).showSnackBar(
      SnackBar(content: Text('Testing connection to ${server.name}...')),
    );
    try {
      final result = await _api.testMCPServer(server.id);
      if (mounted) {
        if (result['success'] == true) {
          final tools = List<String>.from(result['tools']);
          showDialog(
            context: context,
            builder: (ctx) => AlertDialog(
              backgroundColor: const Color(0xFF1C1C26),
              title: const Row(
                children: [
                  Icon(Icons.check_circle_outline, color: Colors.green),
                  SizedBox(width: 12),
                  Text('Connection Success'),
                ],
              ),
              content: Column(
                mainAxisSize: MainAxisSize.min,
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text('Discovered ${tools.length} tools:'),
                  const SizedBox(height: 12),
                  ...tools.map((t) => Padding(
                    padding: const EdgeInsets.only(bottom: 4),
                    child: Text('• $t', style: const TextStyle(fontFamily: 'monospace', fontSize: 12)),
                  )),
                ],
              ),
              actions: [
                TextButton(onPressed: () => Navigator.pop(ctx), child: const Text('Close')),
              ],
            ),
          );
        } else {
          showDialog(
            context: context,
            builder: (ctx) => AlertDialog(
              backgroundColor: const Color(0xFF1C1C26),
              title: const Row(
                children: [
                  Icon(Icons.error_outline, color: Colors.red),
                  SizedBox(width: 12),
                  Text('Connection Failed'),
                ],
              ),
              content: Text(result['error'] ?? 'Unknown error'),
              actions: [
                TextButton(onPressed: () => Navigator.pop(ctx), child: const Text('Close')),
              ],
            ),
          );
        }
      }
    } catch (e) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text('Error: $e')));
      }
    }
  }

  Future<void> _deleteServer(MCPServer server) async {
    try {
      await _api.deleteMCPServer(server.id);
      _loadServers();
    } catch (e) {
      ScaffoldMessenger.of(context)
          .showSnackBar(SnackBar(content: Text('Error: $e')));
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: const Color(0xFF0D0D12),
      appBar: AppBar(
        title: const Text('MCP Servers'),
        backgroundColor: Colors.transparent,
        elevation: 0,
        actions: [
          IconButton(
            icon: const Icon(Icons.refresh),
            onPressed: _loadServers,
          ),
        ],
      ),
      body: _isLoading
          ? const Center(child: CircularProgressIndicator())
          : _error != null
              ? Center(
                  child: Text(_error!, style: const TextStyle(color: Colors.red)))
              : Column(
                  children: [
                    _buildHeader(),
                    Expanded(
                      child: _servers.isEmpty
                          ? _buildEmptyState()
                          : ListView.builder(
                              padding: const EdgeInsets.all(16),
                              itemCount: _servers.length,
                              itemBuilder: (context, index) =>
                                  _buildServerCard(_servers[index]),
                            ),
                    ),
                  ],
                ),
      floatingActionButton: FloatingActionButton.extended(
        onPressed: () => _showServerDialog(),
        icon: const Icon(Icons.add),
        label: const Text('Connect Server'),
        backgroundColor: const Color(0xFF8B5CF6),
      ),
    );
  }

  Widget _buildHeader() {
    return Container(
      padding: const EdgeInsets.all(24),
      decoration: BoxDecoration(
        color: Colors.white.withOpacity(0.03),
        border:
            Border(bottom: BorderSide(color: Colors.white.withOpacity(0.06))),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          const Text(
            'Extend your AI with Dockerized Tools',
            style: TextStyle(
                fontSize: 20, fontWeight: FontWeight.bold, color: Colors.white),
          ),
          const SizedBox(height: 8),
          Text(
            'Connect Model Context Protocol (MCP) servers from Docker Hub to give your agent access to your infrastructure and data.',
            style: TextStyle(color: Colors.white.withOpacity(0.5)),
          ),
          const SizedBox(height: 16),
          InkWell(
            onTap: () async {
              final url = Uri.parse('https://hub.docker.com/mcp');
              if (await canLaunchUrl(url)) {
                await launchUrl(url);
              }
            },
            child: const Row(
              mainAxisSize: MainAxisSize.min,
              children: [
                Icon(Icons.open_in_new, size: 14, color: Color(0xFF8B5CF6)),
                SizedBox(width: 8),
                Text(
                  'Browse MCP Catalog on Docker Hub',
                  style: TextStyle(
                    color: Color(0xFF8B5CF6),
                    fontWeight: FontWeight.w600,
                    decoration: TextDecoration.underline,
                  ),
                ),
              ],
            ),
          ),
        ],
      ),
    );
  }

  Widget _buildEmptyState() {
    return Center(
      child: Column(
        mainAxisSize: MainAxisSize.min,
        children: [
          Icon(Icons.layers_outlined,
              size: 64, color: Colors.white.withOpacity(0.1)),
          const SizedBox(height: 16),
          const Text('No MCP servers connected',
              style: TextStyle(color: Color(0xFF71717A))),
          const SizedBox(height: 8),
          TextButton(
            onPressed: () => _showServerDialog(),
            child: const Text('Add your first tool server'),
          ),
        ],
      ),
    );
  }

  /// Mask a value for display: show first 4 chars then dots, or all dots if short.
  String _maskValue(String value) {
    if (value.length <= 4) return '****';
    return '${value.substring(0, 4)}${'*' * (value.length - 4).clamp(0, 12)}';
  }

  Widget _buildServerCard(MCPServer server) {
    return Card(
      margin: const EdgeInsets.only(bottom: 12),
      color: const Color(0xFF1C1C26),
      shape: RoundedRectangleBorder(
        borderRadius: BorderRadius.circular(12),
        side: BorderSide(color: Colors.white.withOpacity(0.08)),
      ),
      child: Padding(
        padding: const EdgeInsets.all(16),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              children: [
                Container(
                  width: 40,
                  height: 40,
                  decoration: BoxDecoration(
                    color: const Color(0xFF8B5CF6).withOpacity(0.1),
                    borderRadius: BorderRadius.circular(8),
                  ),
                  child:
                      const Icon(Icons.terminal_rounded, color: Color(0xFF8B5CF6)),
                ),
                const SizedBox(width: 12),
                Expanded(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text(
                        server.name,
                        style: const TextStyle(
                            fontSize: 16, fontWeight: FontWeight.bold),
                      ),
                      Text(
                        server.image,
                        style: TextStyle(
                            fontSize: 12, color: Colors.white.withOpacity(0.4)),
                      ),
                    ],
                  ),
                ),
                Switch(
                  value: server.isActive,
                  onChanged: (_) => _toggleServer(server),
                  activeColor: const Color(0xFF8B5CF6),
                ),
                IconButton(
                  icon: const Icon(Icons.edit_outlined,
                      size: 20, color: Colors.white70),
                  tooltip: 'Edit Config',
                  onPressed: () => _showServerDialog(server: server),
                ),
                IconButton(
                  icon: const Icon(Icons.playlist_add_check_rounded,
                      size: 20, color: Color(0xFF8B5CF6)),
                  tooltip: 'Test Connection',
                  onPressed: () => _testServer(server),
                ),
                IconButton(
                  icon: const Icon(Icons.delete_outline,
                      size: 20, color: Colors.red),
                  onPressed: () => _deleteServer(server),
                ),
              ],
            ),
            if (server.envVars.isNotEmpty) ...[
              const SizedBox(height: 12),
              const Divider(color: Colors.white10),
              const SizedBox(height: 8),
              Text(
                'Environment Variables:',
                style: TextStyle(
                    fontSize: 11,
                    fontWeight: FontWeight.bold,
                    color: Colors.white.withOpacity(0.3)),
              ),
              const SizedBox(height: 4),
              Wrap(
                spacing: 8,
                runSpacing: 4,
                children: server.envVars.entries
                    .map((e) => Container(
                          padding: const EdgeInsets.symmetric(
                              horizontal: 8, vertical: 4),
                          decoration: BoxDecoration(
                            color: Colors.black26,
                            borderRadius: BorderRadius.circular(4),
                          ),
                          child: Text(
                            '${e.key}=${_maskValue(e.value.toString())}',
                            style: const TextStyle(
                                fontSize: 10,
                                fontFamily: 'monospace',
                                color: Color(0xFFA1A1AA)),
                          ),
                        ))
                    .toList(),
              ),
            ],
            if (server.args.isNotEmpty) ...[
              const SizedBox(height: 8),
              Text(
                'Container Arguments:',
                style: TextStyle(
                    fontSize: 11,
                    fontWeight: FontWeight.bold,
                    color: Colors.white.withOpacity(0.3)),
              ),
              const SizedBox(height: 4),
              Wrap(
                spacing: 8,
                runSpacing: 4,
                children: server.args.entries
                    .map((e) => Container(
                          padding: const EdgeInsets.symmetric(
                              horizontal: 8, vertical: 4),
                          decoration: BoxDecoration(
                            color: Colors.black26,
                            borderRadius: BorderRadius.circular(4),
                          ),
                          child: Text(
                            '--${e.key}=${e.value}',
                            style: const TextStyle(
                                fontSize: 10,
                                fontFamily: 'monospace',
                                color: Color(0xFFA1A1AA)),
                          ),
                        ))
                    .toList(),
              ),
            ],
          ],
        ),
      ),
    );
  }
}


// ── Helper class for key-value entries ──────────────────────────────

class _KVEntry {
  final TextEditingController key;
  final TextEditingController value;

  _KVEntry({required this.key, required this.value});

  void dispose() {
    key.dispose();
    value.dispose();
  }
}


// ── Dialog content as StatefulWidget (so KV lists can update) ───────

class _ServerDialogContent extends StatefulWidget {
  final TextEditingController nameController;
  final TextEditingController imageController;
  final List<_KVEntry> envEntries;
  final List<_KVEntry> argEntries;
  final bool isEdit;
  final Future<void> Function(Map<String, dynamic> env, Map<String, dynamic> args) onSave;
  final VoidCallback onCancel;

  const _ServerDialogContent({
    required this.nameController,
    required this.imageController,
    required this.envEntries,
    required this.argEntries,
    required this.isEdit,
    required this.onSave,
    required this.onCancel,
  });

  @override
  State<_ServerDialogContent> createState() => _ServerDialogContentState();
}

class _ServerDialogContentState extends State<_ServerDialogContent> {
  bool _isSaving = false;

  Map<String, dynamic> _entriesToMap(List<_KVEntry> entries) {
    final map = <String, dynamic>{};
    for (final e in entries) {
      final k = e.key.text.trim();
      if (k.isNotEmpty) {
        map[k] = e.value.text;
      }
    }
    return map;
  }

  Widget _buildKVEditor({
    required String label,
    required IconData icon,
    required List<_KVEntry> entries,
    required String keyHint,
    required String valueHint,
    bool obscureValues = false,
  }) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Row(
          children: [
            Text(
              label,
              style: TextStyle(
                fontSize: 12,
                fontWeight: FontWeight.w600,
                color: Colors.white.withOpacity(0.4),
                letterSpacing: 0.5,
              ),
            ),
            const Spacer(),
            InkWell(
              onTap: () {
                setState(() {
                  entries.add(_KVEntry(
                    key: TextEditingController(),
                    value: TextEditingController(),
                  ));
                });
              },
              child: Container(
                padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 4),
                decoration: BoxDecoration(
                  color: const Color(0xFF8B5CF6).withOpacity(0.1),
                  borderRadius: BorderRadius.circular(6),
                ),
                child: Row(
                  mainAxisSize: MainAxisSize.min,
                  children: [
                    Icon(Icons.add, size: 14, color: const Color(0xFF8B5CF6)),
                    const SizedBox(width: 4),
                    Text('Add', style: TextStyle(fontSize: 11, color: const Color(0xFF8B5CF6))),
                  ],
                ),
              ),
            ),
          ],
        ),
        const SizedBox(height: 8),
        if (entries.isEmpty)
          Container(
            padding: const EdgeInsets.all(16),
            decoration: BoxDecoration(
              color: Colors.black.withOpacity(0.15),
              borderRadius: BorderRadius.circular(10),
              border: Border.all(color: Colors.white.withOpacity(0.04)),
            ),
            child: Center(
              child: Text(
                'No entries. Click Add to add one.',
                style: TextStyle(fontSize: 12, color: Colors.white.withOpacity(0.2)),
              ),
            ),
          )
        else
          ...entries.asMap().entries.map((indexed) {
            final i = indexed.key;
            final entry = indexed.value;
            return Padding(
              padding: const EdgeInsets.only(bottom: 8),
              child: Row(
                children: [
                  Expanded(
                    flex: 2,
                    child: TextField(
                      controller: entry.key,
                      style: const TextStyle(color: Colors.white, fontSize: 13, fontFamily: 'monospace'),
                      decoration: InputDecoration(
                        hintText: keyHint,
                        hintStyle: TextStyle(color: Colors.white.withOpacity(0.15)),
                        filled: true,
                        fillColor: Colors.black.withOpacity(0.2),
                        isDense: true,
                        contentPadding: const EdgeInsets.symmetric(horizontal: 12, vertical: 12),
                        enabledBorder: OutlineInputBorder(
                          borderRadius: BorderRadius.circular(8),
                          borderSide: BorderSide(color: Colors.white.withOpacity(0.05)),
                        ),
                        focusedBorder: OutlineInputBorder(
                          borderRadius: BorderRadius.circular(8),
                          borderSide: const BorderSide(color: Color(0xFF8B5CF6), width: 1.5),
                        ),
                      ),
                    ),
                  ),
                  Padding(
                    padding: const EdgeInsets.symmetric(horizontal: 6),
                    child: Text('=', style: TextStyle(color: Colors.white.withOpacity(0.2), fontSize: 16)),
                  ),
                  Expanded(
                    flex: 3,
                    child: TextField(
                      controller: entry.value,
                      obscureText: obscureValues,
                      style: const TextStyle(color: Colors.white, fontSize: 13, fontFamily: 'monospace'),
                      decoration: InputDecoration(
                        hintText: valueHint,
                        hintStyle: TextStyle(color: Colors.white.withOpacity(0.15)),
                        filled: true,
                        fillColor: Colors.black.withOpacity(0.2),
                        isDense: true,
                        contentPadding: const EdgeInsets.symmetric(horizontal: 12, vertical: 12),
                        enabledBorder: OutlineInputBorder(
                          borderRadius: BorderRadius.circular(8),
                          borderSide: BorderSide(color: Colors.white.withOpacity(0.05)),
                        ),
                        focusedBorder: OutlineInputBorder(
                          borderRadius: BorderRadius.circular(8),
                          borderSide: const BorderSide(color: Color(0xFF8B5CF6), width: 1.5),
                        ),
                      ),
                    ),
                  ),
                  const SizedBox(width: 4),
                  InkWell(
                    onTap: () {
                      setState(() {
                        entries[i].dispose();
                        entries.removeAt(i);
                      });
                    },
                    child: Padding(
                      padding: const EdgeInsets.all(4),
                      child: Icon(Icons.close, size: 16, color: Colors.red.withOpacity(0.6)),
                    ),
                  ),
                ],
              ),
            );
          }),
      ],
    );
  }

  Widget _buildModernInput({
    required TextEditingController controller,
    required String label,
    required String hint,
    required IconData icon,
    int maxLines = 1,
  }) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text(
          label,
          style: TextStyle(
            fontSize: 12,
            fontWeight: FontWeight.w600,
            color: Colors.white.withOpacity(0.4),
            letterSpacing: 0.5,
          ),
        ),
        const SizedBox(height: 8),
        TextField(
          controller: controller,
          maxLines: maxLines,
          style: const TextStyle(color: Colors.white, fontSize: 14),
          decoration: InputDecoration(
            hintText: hint,
            hintStyle: TextStyle(color: Colors.white.withOpacity(0.2)),
            prefixIcon: Icon(icon, size: 20, color: Colors.white.withOpacity(0.3)),
            filled: true,
            fillColor: Colors.black.withOpacity(0.2),
            contentPadding: const EdgeInsets.symmetric(horizontal: 16, vertical: 16),
            enabledBorder: OutlineInputBorder(
              borderRadius: BorderRadius.circular(14),
              borderSide: BorderSide(color: Colors.white.withOpacity(0.05)),
            ),
            focusedBorder: OutlineInputBorder(
              borderRadius: BorderRadius.circular(14),
              borderSide: const BorderSide(color: Color(0xFF8B5CF6), width: 1.5),
            ),
          ),
        ),
      ],
    );
  }

  @override
  Widget build(BuildContext context) {
    return Center(
      child: Material(
        color: Colors.transparent,
        child: Container(
          width: 520,
          constraints: BoxConstraints(maxHeight: MediaQuery.of(context).size.height * 0.85),
          decoration: BoxDecoration(
            color: const Color(0xFF1C1C26),
            borderRadius: BorderRadius.circular(28),
            border: Border.all(color: Colors.white.withOpacity(0.08)),
            boxShadow: [
              BoxShadow(
                color: Colors.black.withOpacity(0.4),
                blurRadius: 40,
                spreadRadius: 10,
              ),
            ],
          ),
          child: SingleChildScrollView(
            padding: const EdgeInsets.all(32),
            child: Column(
              mainAxisSize: MainAxisSize.min,
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Row(
                  children: [
                    Container(
                      padding: const EdgeInsets.all(10),
                      decoration: BoxDecoration(
                        color: const Color(0xFF8B5CF6).withOpacity(0.15),
                        borderRadius: BorderRadius.circular(12),
                      ),
                      child: Icon(
                        widget.isEdit ? Icons.edit_note_rounded : Icons.add_link_rounded,
                        color: const Color(0xFF8B5CF6),
                      ),
                    ),
                    const SizedBox(width: 16),
                    Text(
                      widget.isEdit ? 'Edit MCP Server' : 'Connect MCP Server',
                      style: const TextStyle(
                        fontSize: 22,
                        fontWeight: FontWeight.bold,
                        color: Colors.white,
                      ),
                    ),
                  ],
                ),
                const SizedBox(height: 24),
                _buildModernInput(
                  controller: widget.nameController,
                  label: 'Server Name',
                  hint: 'e.g. Temporal Tooling',
                  icon: Icons.label_outline_rounded,
                ),
                const SizedBox(height: 16),
                _buildModernInput(
                  controller: widget.imageController,
                  label: 'Docker Image',
                  hint: 'e.g. mcp/temporal:latest',
                  icon: Icons.layers_outlined,
                ),
                const SizedBox(height: 20),
                _buildKVEditor(
                  label: 'Environment Variables',
                  icon: Icons.vpn_key_outlined,
                  entries: widget.envEntries,
                  keyHint: 'KEY',
                  valueHint: 'value',
                  obscureValues: false,
                ),
                const SizedBox(height: 20),
                _buildKVEditor(
                  label: 'Container Arguments',
                  icon: Icons.code_rounded,
                  entries: widget.argEntries,
                  keyHint: 'flag',
                  valueHint: 'value (optional)',
                ),
                const SizedBox(height: 32),
                Row(
                  children: [
                    Expanded(
                      child: TextButton(
                        onPressed: widget.onCancel,
                        style: TextButton.styleFrom(
                          padding: const EdgeInsets.symmetric(vertical: 16),
                          shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(14)),
                        ),
                        child: Text(
                          'Cancel',
                          style: TextStyle(color: Colors.white.withOpacity(0.5)),
                        ),
                      ),
                    ),
                    const SizedBox(width: 16),
                    Expanded(
                      child: Container(
                        decoration: BoxDecoration(
                          borderRadius: BorderRadius.circular(14),
                          gradient: const LinearGradient(
                            colors: [Color(0xFF8B5CF6), Color(0xFF6366F1)],
                          ),
                        ),
                        child: ElevatedButton(
                          onPressed: _isSaving
                              ? null
                              : () async {
                                  setState(() => _isSaving = true);
                                  final env = _entriesToMap(widget.envEntries);
                                  final args = _entriesToMap(widget.argEntries);
                                  await widget.onSave(env, args);
                                  if (mounted) setState(() => _isSaving = false);
                                },
                          style: ElevatedButton.styleFrom(
                            backgroundColor: Colors.transparent,
                            shadowColor: Colors.transparent,
                            padding: const EdgeInsets.symmetric(vertical: 16),
                            shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(14)),
                          ),
                          child: _isSaving
                              ? const SizedBox(width: 20, height: 20, child: CircularProgressIndicator(strokeWidth: 2, color: Colors.white))
                              : Text(
                                  widget.isEdit ? 'Save Changes' : 'Connect Server',
                                  style: const TextStyle(fontWeight: FontWeight.bold, color: Colors.white),
                                ),
                        ),
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
}
