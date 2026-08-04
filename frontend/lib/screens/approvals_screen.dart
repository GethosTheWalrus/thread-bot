import 'package:flutter/material.dart';
import 'package:threadbot/models/phase2.dart';
import 'package:threadbot/services/phase2_api.dart';

class ApprovalsScreen extends StatefulWidget {
  final Phase2ApiService api;
  const ApprovalsScreen({super.key, required this.api});
  @override
  State<ApprovalsScreen> createState() => _ApprovalsState();
}

class _ApprovalsState extends State<ApprovalsScreen> {
  List<Approval> items = const [];
  String? error;
  bool loading = true;
  @override
  void initState() {
    super.initState();
    load();
  }

  Future<void> load() async {
    try {
      final v = await widget.api.approvals();
      if (mounted)
        setState(() {
          items = v;
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

  Future<void> decide(Approval item, String value) async {
    try {
      await widget.api.decide(item.id, value);
      await load();
    } catch (e) {
      if (mounted)
        ScaffoldMessenger.of(
          context,
        ).showSnackBar(SnackBar(content: Text('$e')));
    }
  }

  @override
  Widget build(BuildContext context) {
    final body = loading
        ? const Center(child: CircularProgressIndicator())
        : error != null
        ? Center(child: Text(error!))
        : items.isEmpty
        ? const Center(child: Text('No pending approvals'))
        : ListView(
            padding: const EdgeInsets.all(16),
            children: [
              for (final item in items)
                Card(
                  child: ExpansionTile(
                    title: Text(item.actionId),
                    subtitle: Text(
                      '${item.riskLevel} • ${item.status}${item.expired ? ' • expired' : ''}${item.expiresAt == null ? '' : ' • expires ${item.expiresAt!.toLocal()}'}',
                    ),
                    children: [
                      ListTile(
                        title: const Text('Target'),
                        subtitle: Text(item.target.toString()),
                      ),
                      if (item.arguments.isNotEmpty)
                        ListTile(
                          title: const Text('Redacted arguments'),
                          subtitle: Text(item.arguments.toString()),
                        ),
                      if (item.explanation.isNotEmpty)
                        ListTile(
                          title: const Text('Policy explanation'),
                          subtitle: Text(item.explanation.toString()),
                        ),
                      OverflowBar(
                        children: [
                          TextButton(
                            onPressed: item.expired
                                ? null
                                : () => decide(item, 'denied'),
                            child: const Text('Deny'),
                          ),
                          FilledButton(
                            onPressed: item.expired
                                ? null
                                : () => decide(item, 'approved'),
                            child: const Text('Approve'),
                          ),
                        ],
                      ),
                    ],
                  ),
                ),
            ],
          );
    return Scaffold(
      appBar: AppBar(
        title: const Text('Approvals'),
        actions: [IconButton(onPressed: load, icon: const Icon(Icons.refresh))],
      ),
      body: body,
    );
  }
}
