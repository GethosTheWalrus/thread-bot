import 'package:flutter/material.dart';
import 'dart:convert';
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
    final envController = TextEditingController(
        text: server == null
            ? '{\n  "TEMPORAL_HOST": "temporal:7233",\n  "TEMPORAL_NAMESPACE": "default"\n}'
            : const JsonEncoder.withIndent('  ').convert(server.envVars));

    showGeneralDialog(
      context: context,
      barrierDismissible: true,
      barrierLabel: 'Dismiss',
      transitionDuration: const Duration(milliseconds: 300),
      pageBuilder: (ctx, anim1, anim2) => Center(
        child: Material(
          color: Colors.transparent,
          child: Container(
            width: 450,
            padding: const EdgeInsets.all(32),
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
                        server == null ? Icons.add_link_rounded : Icons.edit_note_rounded,
                        color: const Color(0xFF8B5CF6),
                      ),
                    ),
                    const SizedBox(width: 16),
                    Text(
                      server == null ? 'Connect MCP Server' : 'Edit MCP Server',
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
                  controller: nameController,
                  label: 'Server Name',
                  hint: 'e.g. Temporal Tooling',
                  icon: Icons.label_outline_rounded,
                ),
                const SizedBox(height: 16),
                _buildModernInput(
                  controller: imageController,
                  label: 'Docker Image',
                  hint: 'e.g. mcp/temporal:latest',
                  icon: Icons.layers_outlined,
                ),
                const SizedBox(height: 16),
                _buildModernInput(
                  controller: envController,
                  label: 'Environment Variables (JSON)',
                  hint: '{"KEY": "VALUE"}',
                  icon: Icons.code_rounded,
                  maxLines: 4,
                ),
                const SizedBox(height: 32),
                Row(
                  children: [
                    Expanded(
                      child: TextButton(
                        onPressed: () => Navigator.pop(ctx),
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
                          onPressed: () async {
                            try {
                              final String text = envController.text.trim();
                              final Map<String, dynamic> envRaw = text.isEmpty
                                  ? <String, dynamic>{}
                                  : Map<String, dynamic>.from(jsonDecode(text));
                              
                              final Map<String, String> env = envRaw.map((k, v) => MapEntry(k, v.toString()));

                              if (server == null) {
                                await _api.createMCPServer(
                                  name: nameController.text,
                                  image: imageController.text,
                                  envVars: env,
                                );
                              } else {
                                await _api.updateMCPServer(
                                  server.id,
                                  nameController.text,
                                  imageController.text,
                                  env,
                                );
                              }
                              Navigator.pop(ctx);
                              _loadServers();
                            } catch (e) {
                              ScaffoldMessenger.of(context).showSnackBar(
                                  SnackBar(content: Text('Error: $e')));
                            }
                          },
                          style: ElevatedButton.styleFrom(
                            backgroundColor: Colors.transparent,
                            shadowColor: Colors.transparent,
                            padding: const EdgeInsets.symmetric(vertical: 16),
                            shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(14)),
                          ),
                          child: Text(
                            server == null ? 'Connect Server' : 'Save Changes',
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
      transitionBuilder: (ctx, anim1, anim2, child) => FadeTransition(
        opacity: anim1,
        child: ScaleTransition(
          scale: anim1.drive(Tween(begin: 0.9, end: 1.0).chain(CurveTween(curve: Curves.easeOutCubic))),
          child: child,
        ),
      ),
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
            child: Row(
              mainAxisSize: MainAxisSize.min,
              children: [
                const Icon(Icons.open_in_new, size: 14, color: Color(0xFF8B5CF6)),
                const SizedBox(width: 8),
                const Text(
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
                            '${e.key}=${e.value}',
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
