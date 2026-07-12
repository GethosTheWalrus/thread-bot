import 'package:flutter/material.dart';
import 'package:threadbot/models/skill.dart';
import 'package:threadbot/services/api_service.dart';

class SkillsScreen extends StatefulWidget {
  const SkillsScreen({super.key});

  @override
  State<SkillsScreen> createState() => _SkillsScreenState();
}

class _SkillsScreenState extends State<SkillsScreen> {
  final ApiService _api = ApiService();
  List<Skill> _skills = [];
  bool _isLoading = true;
  String? _error;

  @override
  void initState() {
    super.initState();
    _loadSkills();
  }

  Future<void> _loadSkills() async {
    setState(() => _isLoading = true);
    try {
      final skills = await _api.getSkills();
      if (!mounted) return;
      setState(() {
        _skills = skills;
        _isLoading = false;
        _error = null;
      });
    } catch (e) {
      if (!mounted) return;
      setState(() {
        _error = e.toString();
        _isLoading = false;
      });
    }
  }

  Future<void> _showSkillDialog({Skill? skill}) async {
    final nameController = TextEditingController(text: skill?.name ?? '');
    final descriptionController = TextEditingController(text: skill?.description ?? '');
    final contentController = TextEditingController(text: skill?.content ?? '');

    await showDialog<void>(
      context: context,
      builder: (ctx) => AlertDialog(
        backgroundColor: const Color(0xFF1C1C26),
        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(16)),
        title: Text(skill == null ? 'Add Skill' : 'Edit Skill'),
        content: SizedBox(
          width: 680,
          child: SingleChildScrollView(
            child: Column(
              mainAxisSize: MainAxisSize.min,
              children: [
                TextField(
                  controller: nameController,
                  decoration: const InputDecoration(labelText: 'Name'),
                ),
                const SizedBox(height: 12),
                TextField(
                  controller: descriptionController,
                  decoration: const InputDecoration(labelText: 'Description'),
                ),
                const SizedBox(height: 12),
                TextField(
                  controller: contentController,
                  minLines: 10,
                  maxLines: 18,
                  decoration: const InputDecoration(
                    labelText: 'Skill instructions',
                    alignLabelWithHint: true,
                    hintText: 'Reusable guidance, procedure, style, or domain knowledge for ThreadBot to apply when relevant.',
                  ),
                  style: const TextStyle(fontFamily: 'monospace', fontSize: 13),
                ),
              ],
            ),
          ),
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(ctx),
            child: const Text('Cancel'),
          ),
          FilledButton(
            onPressed: () async {
              final name = nameController.text.trim();
              final content = contentController.text.trim();
              if (name.isEmpty || content.isEmpty) return;
              try {
                if (skill == null) {
                  await _api.createSkill(
                    name: name,
                    description: descriptionController.text.trim(),
                    content: content,
                  );
                } else {
                  await _api.updateSkill(
                    skill.id,
                    name: name,
                    description: descriptionController.text.trim(),
                    content: content,
                  );
                }
                if (!mounted || !ctx.mounted) return;
                Navigator.pop(ctx);
                _loadSkills();
              } catch (e) {
                if (!mounted) return;
                ScaffoldMessenger.of(context).showSnackBar(
                  SnackBar(content: Text('Error: $e')),
                );
              }
            },
            child: const Text('Save'),
          ),
        ],
      ),
    );

    nameController.dispose();
    descriptionController.dispose();
    contentController.dispose();
  }

  Future<void> _toggleSkill(Skill skill) async {
    try {
      await _api.toggleSkill(skill.id);
      _loadSkills();
    } catch (e) {
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text('Error: $e')));
    }
  }

  Future<void> _deleteSkill(Skill skill) async {
    try {
      await _api.deleteSkill(skill.id);
      _loadSkills();
    } catch (e) {
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text('Error: $e')));
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: const Color(0xFF0D0D12),
      appBar: AppBar(
        title: const Text('Skills'),
        backgroundColor: Colors.transparent,
        elevation: 0,
        actions: [
          IconButton(icon: const Icon(Icons.refresh), onPressed: _loadSkills),
        ],
      ),
      body: _isLoading
          ? const Center(child: CircularProgressIndicator())
          : _error != null
              ? Center(child: Text(_error!, style: const TextStyle(color: Colors.red)))
              : Column(
                  children: [
                    _buildHeader(),
                    Expanded(
                      child: _skills.isEmpty
                          ? _buildEmptyState()
                          : ListView.builder(
                              padding: const EdgeInsets.all(16),
                              itemCount: _skills.length,
                              itemBuilder: (context, index) => _buildSkillCard(_skills[index]),
                            ),
                    ),
                  ],
                ),
      floatingActionButton: FloatingActionButton.extended(
        onPressed: () => _showSkillDialog(),
        icon: const Icon(Icons.add),
        label: const Text('Add Skill'),
        backgroundColor: const Color(0xFF8B5CF6),
      ),
    );
  }

  Widget _buildHeader() {
    return Container(
      width: double.infinity,
      padding: const EdgeInsets.all(24),
      decoration: BoxDecoration(
        color: Colors.white.withValues(alpha: 0.03),
        border: Border(bottom: BorderSide(color: Colors.white.withValues(alpha: 0.06))),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          const Text(
            'Teach ThreadBot Reusable Skills',
            style: TextStyle(fontSize: 20, fontWeight: FontWeight.bold, color: Colors.white),
          ),
          const SizedBox(height: 8),
          Text(
            'Skills are reusable instruction modules injected into ThreadBot before each response. Use them for workflows, preferences, domain guidance, and house style.',
            style: TextStyle(color: Colors.white.withValues(alpha: 0.5)),
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
          Icon(Icons.school_outlined, size: 64, color: Colors.white.withValues(alpha: 0.1)),
          const SizedBox(height: 16),
          const Text('No skills yet', style: TextStyle(color: Color(0xFF71717A))),
          const SizedBox(height: 8),
          TextButton(onPressed: () => _showSkillDialog(), child: const Text('Add your first skill')),
        ],
      ),
    );
  }

  Widget _buildSkillCard(Skill skill) {
    return Card(
      margin: const EdgeInsets.only(bottom: 12),
      color: const Color(0xFF1C1C26),
      shape: RoundedRectangleBorder(
        borderRadius: BorderRadius.circular(12),
        side: BorderSide(color: Colors.white.withValues(alpha: 0.08)),
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
                    color: const Color(0xFF8B5CF6).withValues(alpha: 0.1),
                    borderRadius: BorderRadius.circular(8),
                  ),
                  child: const Icon(Icons.school_rounded, color: Color(0xFF8B5CF6)),
                ),
                const SizedBox(width: 12),
                Expanded(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text(skill.name, style: const TextStyle(fontSize: 16, fontWeight: FontWeight.bold)),
                      if (skill.description.isNotEmpty)
                        Text(
                          skill.description,
                          maxLines: 2,
                          overflow: TextOverflow.ellipsis,
                          style: TextStyle(fontSize: 12, color: Colors.white.withValues(alpha: 0.45)),
                        ),
                    ],
                  ),
                ),
                Switch(
                  value: skill.isActive,
                  onChanged: (_) => _toggleSkill(skill),
                  activeThumbColor: const Color(0xFF8B5CF6),
                ),
                IconButton(
                  icon: const Icon(Icons.edit_outlined, size: 20, color: Colors.white70),
                  onPressed: () => _showSkillDialog(skill: skill),
                ),
                IconButton(
                  icon: const Icon(Icons.delete_outline, size: 20, color: Colors.red),
                  onPressed: () => _deleteSkill(skill),
                ),
              ],
            ),
            const SizedBox(height: 12),
            Text(
              skill.content,
              maxLines: 5,
              overflow: TextOverflow.ellipsis,
              style: TextStyle(
                color: Colors.white.withValues(alpha: 0.65),
                fontSize: 13,
                height: 1.35,
              ),
            ),
          ],
        ),
      ),
    );
  }
}
