import 'dart:async';
import 'package:flutter/material.dart';
import 'package:threadbot/models/osrs_loadout.dart';
import 'package:threadbot/services/api_service.dart';

class OsrsLoadoutsScreen extends StatefulWidget {
  const OsrsLoadoutsScreen({super.key});
  @override
  State<OsrsLoadoutsScreen> createState() => _OsrsLoadoutsScreenState();
}

class _OsrsLoadoutsScreenState extends State<OsrsLoadoutsScreen> {
  final _api = ApiService();
  List<OsrsLoadout> _items = [];
  OsrsLoadout? _editing;
  OsrsLoadoutPayload _payload = OsrsLoadoutPayload.empty();
  final _name = TextEditingController(), _description = TextEditingController();
  bool _loading = true, _saving = false;
  String? _error;

  @override
  void initState() {
    super.initState();
    _load();
  }

  @override
  void dispose() {
    _name.dispose();
    _description.dispose();
    super.dispose();
  }

  Future<void> _load() async {
    try {
      final x = await _api.getOsrsLoadouts();
      if (mounted)
        setState(() {
          _items = x;
          _loading = false;
        });
    } catch (e) {
      if (mounted)
        setState(() {
          _error = '$e';
          _loading = false;
        });
    }
  }

  void _new() {
    setState(() {
      _editing = null;
      _payload = OsrsLoadoutPayload.empty();
      _name.text = '';
      _description.text = '';
    });
  }

  void _edit(OsrsLoadout x) {
    setState(() {
      _editing = x;
      _payload = x.loadout;
      _name.text = x.name;
      _description.text = x.description ?? '';
    });
  }

  Future<void> _save() async {
    if (_name.text.trim().isEmpty) {
      setState(() => _error = 'Give this loadout a name.');
      return;
    }
    setState(() {
      _saving = true;
      _error = null;
    });
    try {
      final x = _editing == null
          ? await _api.createOsrsLoadout(
              name: _name.text.trim(),
              description: _description.text.trim().isEmpty
                  ? null
                  : _description.text.trim(),
              loadout: _payload,
            )
          : await _api.updateOsrsLoadout(
              _editing!.id,
              expectedRevision: _editing!.revision,
              name: _name.text.trim(),
              description: _description.text.trim(),
              loadout: _payload,
            );
      if (mounted) {
        setState(() {
          _editing = x;
          _items = [..._items.where((i) => i.id != x.id), x];
        });
        _toast('Loadout saved');
      }
    } catch (e) {
      if (mounted) setState(() => _error = '$e');
    } finally {
      if (mounted) setState(() => _saving = false);
    }
  }

  Future<void> _delete(OsrsLoadout x) async {
    try {
      await _api.deleteOsrsLoadout(x.id);
      setState(() => _items.removeWhere((i) => i.id == x.id));
      if (_editing?.id == x.id) _new();
    } catch (e) {
      _toast('$e');
    }
  }

  Future<void> _default(OsrsLoadout x) async {
    try {
      final updated = await _api.setOsrsDefault(x.id);
      setState(
        () => _items = _items
            .map(
              (i) => i.id == updated.id
                  ? updated
                  : OsrsLoadout(
                      id: i.id,
                      name: i.name,
                      sourceType: i.sourceType,
                      loadout: i.loadout,
                      revision: i.revision,
                      isDefault: false,
                      description: i.description,
                      sourceRef: i.sourceRef,
                      engineRevision: i.engineRevision,
                    ),
            )
            .toList(),
      );
    } catch (e) {
      _toast('$e');
    }
  }

  void _toast(String text) => ScaffoldMessenger.of(context).showSnackBar(
    SnackBar(content: Text(text), behavior: SnackBarBehavior.floating),
  );

  @override
  Widget build(BuildContext context) {
    final wide = MediaQuery.sizeOf(context).width > 900;
    return Scaffold(
      appBar: AppBar(
        title: const Text('OSRS Loadouts'),
        actions: [
          IconButton(onPressed: _load, icon: const Icon(Icons.refresh)),
          if (wide)
            Padding(
              padding: const EdgeInsets.only(right: 20),
              child: FilledButton.icon(
                onPressed: _new,
                icon: const Icon(Icons.add),
                label: const Text('New loadout'),
              ),
            ),
        ],
      ),
      body: _loading
          ? const Center(child: CircularProgressIndicator())
          : _error != null && _items.isEmpty
          ? Center(child: Text(_error!))
          : Padding(
              padding: const EdgeInsets.all(24),
              child: wide
                  ? Row(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        SizedBox(width: 330, child: _list()),
                        const SizedBox(width: 24),
                        Expanded(child: _editor()),
                      ],
                    )
                  : _editing == null
                  ? _list()
                  : _editor(),
            ),
    );
  }

  Widget _list() {
    if (_items.isEmpty) {
      return Center(
        child: ConstrainedBox(
          constraints: const BoxConstraints(maxWidth: 520),
          child: Card(
            child: Padding(
              padding: const EdgeInsets.all(32),
              child: Column(
                mainAxisSize: MainAxisSize.min,
                children: [
                  const Icon(
                    Icons.shield_outlined,
                    size: 52,
                    color: Color(0xFFC4B5FD),
                  ),
                  const SizedBox(height: 16),
                  Text(
                    'Build your first loadout',
                    style: Theme.of(context).textTheme.headlineSmall,
                  ),
                  const SizedBox(height: 8),
                  const Text(
                    'Save gear, stats and combat settings for quick, consistent OSRS answers.',
                    textAlign: TextAlign.center,
                  ),
                  const SizedBox(height: 24),
                  Wrap(
                    spacing: 10,
                    children: [
                      FilledButton.icon(
                        onPressed: _import,
                        icon: const Icon(Icons.link),
                        label: const Text('Import Wiki Link'),
                      ),
                      OutlinedButton.icon(
                        onPressed: _new,
                        icon: const Icon(Icons.edit_outlined),
                        label: const Text('Create manually'),
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
    return ListView(
      padding: const EdgeInsets.only(bottom: 20),
      children: [
        ..._items.map(_tile),
        if (MediaQuery.sizeOf(context).width <= 900)
          Padding(
            padding: const EdgeInsets.only(top: 12),
            child: FilledButton.icon(
              onPressed: _new,
              icon: const Icon(Icons.add),
              label: const Text('New loadout'),
            ),
          ),
      ],
    );
  }

  Widget _tile(OsrsLoadout x) => Card(
    margin: const EdgeInsets.only(bottom: 10),
    child: ListTile(
      onTap: () => _edit(x),
      leading: CircleAvatar(
        backgroundColor: const Color(0xFF8B5CF6).withValues(alpha: .18),
        child: const Icon(Icons.shield_outlined, color: Color(0xFFC4B5FD)),
      ),
      title: Text(x.name, style: const TextStyle(fontWeight: FontWeight.w700)),
      subtitle: Text(
        '${x.sourceType} · revision ${x.revision}${x.isDefault ? ' · DEFAULT' : ''}',
      ),
      trailing: PopupMenuButton<String>(
        onSelected: (v) {
          if (v == 'default') _default(x);
          if (v == 'delete') _confirmDelete(x);
          if (v == 'clone') _clone(x);
        },
        itemBuilder: (_) => [
          if (!x.isDefault)
            const PopupMenuItem(
              value: 'default',
              child: Text('Set as default'),
            ),
          const PopupMenuItem(value: 'clone', child: Text('Clone')),
          const PopupMenuItem(value: 'delete', child: Text('Delete')),
        ],
      ),
    ),
  );
  Widget _editor() => SingleChildScrollView(
    child: Card(
      child: Padding(
        padding: const EdgeInsets.all(24),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              children: [
                if (MediaQuery.sizeOf(context).width <= 900)
                  IconButton(
                    onPressed: _new,
                    icon: const Icon(Icons.arrow_back),
                  ),
                Expanded(
                  child: Text(
                    _editing == null ? 'New loadout' : 'Edit loadout',
                    style: Theme.of(context).textTheme.headlineSmall,
                  ),
                ),
                FilledButton.icon(
                  onPressed: _saving ? null : _save,
                  icon: _saving
                      ? const SizedBox(
                          width: 16,
                          height: 16,
                          child: CircularProgressIndicator(strokeWidth: 2),
                        )
                      : const Icon(Icons.save_outlined),
                  label: const Text('Save'),
                ),
              ],
            ),
            const SizedBox(height: 20),
            if (_error != null)
              Text(
                _error!,
                style: TextStyle(color: Theme.of(context).colorScheme.error),
              ),
            _field(_name, 'Name', 'e.g. Vorkath melee'),
            _field(_description, 'Description', 'Optional notes', maxLines: 2),
            const SizedBox(height: 22),
            _section('Equipment', _equipment()),
            _section('Levels and boosts', _stats()),
            _section('Prayers and potions', _lists()),
            _section('Buffs', _buffs()),
            _section('Combat', _combat()),
          ],
        ),
      ),
    ),
  );
  Widget _section(String title, Widget child) => Padding(
    padding: const EdgeInsets.only(top: 18),
    child: Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text(
          title,
          style: const TextStyle(fontSize: 16, fontWeight: FontWeight.w700),
        ),
        const SizedBox(height: 10),
        child,
      ],
    ),
  );
  Widget _field(
    TextEditingController c,
    String label,
    String hint, {
    int maxLines = 1,
  }) => Padding(
    padding: const EdgeInsets.only(bottom: 12),
    child: TextField(
      controller: c,
      maxLines: maxLines,
      decoration: InputDecoration(labelText: label, hintText: hint),
    ),
  );
  Widget _equipment() => LayoutBuilder(
    builder: (_, box) => GridView.count(
      shrinkWrap: true,
      physics: const NeverScrollableScrollPhysics(),
      crossAxisCount: box.maxWidth > 700
          ? 4
          : box.maxWidth > 420
          ? 3
          : 2,
      childAspectRatio: 2.7,
      mainAxisSpacing: 8,
      crossAxisSpacing: 8,
      children: osrsSlots.map((slot) {
        final item = _payload.equipment[slot];
        return InkWell(
          onTap: () => _pickItem(slot),
          borderRadius: BorderRadius.circular(12),
          child: Container(
            padding: const EdgeInsets.all(10),
            decoration: BoxDecoration(
              color: Colors.white.withValues(alpha: .04),
              borderRadius: BorderRadius.circular(12),
              border: Border.all(
                color: item == null
                    ? Colors.white.withValues(alpha: .08)
                    : const Color(0xFF8B5CF6).withValues(alpha: .6),
              ),
            ),
            child: Row(
              children: [
                Icon(
                  Icons.circle_outlined,
                  size: 17,
                  color: item == null
                      ? Colors.white38
                      : const Color(0xFFC4B5FD),
                ),
                const SizedBox(width: 8),
                Expanded(
                  child: Text(
                    item?.name ?? slot.toUpperCase(),
                    maxLines: 2,
                    overflow: TextOverflow.ellipsis,
                    style: TextStyle(
                      fontSize: 12,
                      color: item == null ? Colors.white54 : Colors.white,
                      fontWeight: FontWeight.w600,
                    ),
                  ),
                ),
                if (item != null)
                  IconButton(
                    visualDensity: VisualDensity.compact,
                    onPressed: () =>
                        setState(() => _replaceEquipment(slot, null)),
                    icon: const Icon(Icons.close, size: 16),
                  ),
              ],
            ),
          ),
        );
      }).toList(),
    ),
  );
  void _replaceEquipment(String slot, OsrsEquipmentItem? item) {
    _payload = OsrsLoadoutPayload(
      equipment: {..._payload.equipment, slot: item},
      skills: _payload.skills,
      boosts: _payload.boosts,
      prayers: _payload.prayers,
      potions: _payload.potions,
      buffs: _payload.buffs,
      combat: _payload.combat,
    );
  }

  Widget _stats() => LayoutBuilder(
    builder: (_, box) => Wrap(
      spacing: 12,
      runSpacing: 10,
      children: [
        ..._payload.skills.keys.map(
          (s) => SizedBox(
            width: box.maxWidth > 700 ? 130 : 100,
            child: _number(
              s.toUpperCase(),
              _payload.skills[s]!,
              (v) => _changeStat(s, v, false),
              min: 1,
              max: 126,
              helper: 'level',
            ),
          ),
        ),
        ..._payload.boosts.keys.map(
          (s) => SizedBox(
            width: box.maxWidth > 700 ? 130 : 100,
            child: _number(
              '${s.toUpperCase()} boost',
              _payload.boosts[s]!,
              (v) => _changeStat(s, v, true),
              min: -126,
              max: 126,
              helper: 'boost',
            ),
          ),
        ),
      ],
    ),
  );
  void _changeStat(String key, int value, bool boost) {
    final map = {...(boost ? _payload.boosts : _payload.skills), key: value};
    _payload = OsrsLoadoutPayload(
      equipment: _payload.equipment,
      skills: boost ? _payload.skills : map,
      boosts: boost ? map : _payload.boosts,
      prayers: _payload.prayers,
      potions: _payload.potions,
      buffs: _payload.buffs,
      combat: _payload.combat,
    );
  }

  Widget _number(
    String label,
    int value,
    ValueChanged<int> onChanged, {
    required int min,
    required int max,
    String? helper,
  }) => _NumberField(
    key: ValueKey(label),
    label: label,
    value: value,
    onChanged: onChanged,
    min: min,
    max: max,
    helper: helper,
  );

  Widget _smallList(
    String label,
    List<int> values,
    ValueChanged<List<int>> update,
  ) => _SmallListField(
    key: ValueKey(label),
    label: label,
    values: values,
    update: update,
  );

  Widget _lists() => Wrap(
    spacing: 12,
    children: [
      _smallList(
        'Prayer ids',
        _payload.prayers,
        (x) => setState(() => _payload = _copy(prayers: x)),
      ),
      _smallList(
        'Potion ids',
        _payload.potions,
        (x) => setState(() => _payload = _copy(potions: x)),
      ),
    ],
  );

  Widget _buffs() => Wrap(
    spacing: 8,
    runSpacing: 4,
    children: _payload.buffs.entries.map((e) {
      final boolValue = e.value is bool;
      return boolValue
          ? FilterChip(
              label: Text(_pretty(e.key)),
              selected: e.value == true,
              onSelected: (v) => setState(
                () => _payload = _copy(buffs: {..._payload.buffs, e.key: v}),
              ),
            )
          : SizedBox(
              width: 180,
              child: _number(
                _pretty(e.key),
                (e.value as num?)?.toInt() ?? 0,
                (v) => setState(
                  () => _payload = _copy(buffs: {..._payload.buffs, e.key: v}),
                ),
                min: e.key == 'chinchompa_distance' ? 1 : 0,
                max: e.key == 'soulreaper_stacks' ? 5 : 126,
              ),
            );
    }).toList(),
  );
  Widget _combat() => Wrap(
    spacing: 12,
    runSpacing: 10,
    children: [
      _select(
        'Stance',
        [
          'Accurate',
          'Aggressive',
          'Autocast',
          'Controlled',
          'Defensive',
          'Defensive Autocast',
          'Longrange',
          'Rapid',
          'Manual Cast',
        ],
        _payload.combat['stance'],
        (v) => setState(
          () => _payload = _copy(combat: {..._payload.combat, 'stance': v}),
        ),
      ),
      _select(
        'Attack type',
        ['stab', 'slash', 'crush', 'magic', 'ranged'],
        _payload.combat['attack_type'],
        (v) => setState(
          () =>
              _payload = _copy(combat: {..._payload.combat, 'attack_type': v}),
        ),
      ),
      SizedBox(
        width: 220,
        child: TextField(
          decoration: const InputDecoration(labelText: 'Spell'),
          onChanged: (v) =>
              _payload = _copy(combat: {..._payload.combat, 'spell': v}),
        ),
      ),
    ],
  );
  Widget _select(
    String label,
    List<String> values,
    dynamic current,
    ValueChanged<String?> changed,
  ) => SizedBox(
    width: 220,
    child: DropdownButtonFormField<String>(
      initialValue: values.contains(current) ? current : null,
      decoration: InputDecoration(labelText: label),
      items: values
          .map((v) => DropdownMenuItem(value: v, child: Text(v)))
          .toList(),
      onChanged: changed,
    ),
  );
  OsrsLoadoutPayload _copy({
    Map<String, dynamic>? buffs,
    Map<String, dynamic>? combat,
    List<int>? prayers,
    List<int>? potions,
  }) => OsrsLoadoutPayload(
    equipment: _payload.equipment,
    skills: _payload.skills,
    boosts: _payload.boosts,
    prayers: prayers ?? _payload.prayers,
    potions: potions ?? _payload.potions,
    buffs: buffs ?? _payload.buffs,
    combat: combat ?? _payload.combat,
  );
  String _pretty(String x) => x
      .replaceAll('_', ' ')
      .split(' ')
      .map((s) => s.isEmpty ? s : '${s[0].toUpperCase()}${s.substring(1)}')
      .join(' ');

  Future<void> _pickItem(String slot) async {
    final c = TextEditingController();
    Timer? timer;
    List<Map<String, dynamic>> results = [];
    final selected = await showDialog<OsrsEquipmentItem>(
      context: context,
      builder: (ctx) => StatefulBuilder(
        builder: (ctx, refresh) => AlertDialog(
          title: Text('Choose ${_pretty(slot)}'),
          content: SizedBox(
            width: 480,
            height: 420,
            child: Column(
              children: [
                TextField(
                  controller: c,
                  autofocus: true,
                  decoration: const InputDecoration(
                    prefixIcon: Icon(Icons.search),
                    hintText: 'Search items…',
                  ),
                  onChanged: (q) {
                    timer?.cancel();
                    timer = Timer(const Duration(milliseconds: 350), () async {
                      if (q.trim().isEmpty) return;
                      try {
                        final r = await _api.searchOsrsEquipment(q, slot: slot);
                        if (ctx.mounted) refresh(() => results = r);
                      } catch (_) {}
                    });
                  },
                ),
                const SizedBox(height: 12),
                Expanded(
                  child: ListView(
                    children: results
                        .map(
                          (r) => ListTile(
                            title: Text(
                              '${r['name'] ?? r['item_name'] ?? 'Item'}',
                            ),
                            subtitle: Text(
                              'ID ${r['id'] ?? r['item_id'] ?? '?'}${r['version'] == null ? '' : ' · ${r['version']}'}',
                            ),
                            onTap: () => Navigator.pop(
                              ctx,
                              OsrsEquipmentItem(
                                id:
                                    int.tryParse(
                                      '${r['id'] ?? r['item_id'] ?? 0}',
                                    ) ??
                                    0,
                                name:
                                    '${r['name'] ?? r['item_name'] ?? 'Item'}',
                                version: r['version']?.toString(),
                                itemVars: Map<String, dynamic>.from(
                                  (r['itemVars'] as Map?) ??
                                      (r['item_vars'] as Map?) ??
                                      {},
                                ),
                              ),
                            ),
                          ),
                        )
                        .toList(),
                  ),
                ),
              ],
            ),
          ),
          actions: [
            TextButton(
              onPressed: () => Navigator.pop(ctx),
              child: const Text('Cancel'),
            ),
          ],
        ),
      ),
    );
    timer?.cancel();
    if (selected != null && mounted)
      setState(() => _replaceEquipment(slot, selected));
  }

  Future<void> _clone(OsrsLoadout x) async {
    final c = TextEditingController(text: '${x.name} copy');
    final name = await showDialog<String>(
      context: context,
      builder: (ctx) => AlertDialog(
        title: const Text('Clone loadout'),
        content: TextField(
          controller: c,
          autofocus: true,
          decoration: const InputDecoration(labelText: 'Name'),
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(ctx),
            child: const Text('Cancel'),
          ),
          FilledButton(
            onPressed: () => Navigator.pop(ctx, c.text.trim()),
            child: const Text('Clone'),
          ),
        ],
      ),
    );
    if (name?.isNotEmpty == true) {
      try {
        final copy = await _api.cloneOsrsLoadout(x.id, name!);
        setState(() => _items.add(copy));
      } catch (e) {
        _toast('$e');
      }
    }
  }

  Future<void> _confirmDelete(OsrsLoadout x) async {
    final yes = await showDialog<bool>(
      context: context,
      builder: (ctx) => AlertDialog(
        title: const Text('Delete loadout?'),
        content: Text('Delete “${x.name}”?'),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(ctx, false),
            child: const Text('Cancel'),
          ),
          FilledButton(
            onPressed: () => Navigator.pop(ctx, true),
            child: const Text('Delete'),
          ),
        ],
      ),
    );
    if (yes == true) _delete(x);
  }

  Future<void> _import() async {
    final c = TextEditingController();
    final link = await showDialog<String>(
      context: context,
      builder: (ctx) => AlertDialog(
        title: const Text('Import from Wiki'),
        content: TextField(
          controller: c,
          autofocus: true,
          decoration: const InputDecoration(labelText: 'DPS calculator link'),
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(ctx),
            child: const Text('Cancel'),
          ),
          FilledButton(
            onPressed: () => Navigator.pop(ctx, c.text.trim()),
            child: const Text('Preview'),
          ),
        ],
      ),
    );
    if (link == null || link.isEmpty) return;
    try {
      final preview = await _api.previewOsrsWiki(link);
      final raw = preview is List
          ? preview
          : (preview is Map
                ? (preview['loadouts'] ?? preview['results'] ?? [preview])
                : []);
      if (!mounted) return;
      final chosen = await showDialog<Map<String, dynamic>>(
        context: context,
        builder: (ctx) => _ImportDialog(
          raw
              .whereType<Map>()
              .map((x) => Map<String, dynamic>.from(x))
              .toList(),
        ),
      );
      if (chosen != null) {
        final payload = OsrsLoadoutPayload.fromJson(
          Map<String, dynamic>.from(chosen['loadout'] as Map? ?? chosen),
        );
        final imported = await _api.commitOsrsWiki([
          {
            'name': '${chosen['name'] ?? 'Imported loadout'}',
            'description': 'Imported from Wiki',
            'loadout': payload.toJson(),
            'source_type': 'wiki',
            'source_ref': link,
          },
        ]);
        if (mounted && imported.isNotEmpty) {
          setState(() => _items = [..._items, imported.first]);
          _edit(imported.first);
          _toast('Wiki loadout imported');
        }
      }
    } catch (e) {
      _toast('Import failed: $e');
    }
  }
}

class _ImportDialog extends StatefulWidget {
  final List<Map<String, dynamic>> options;
  const _ImportDialog(this.options);
  @override
  State<_ImportDialog> createState() => _ImportDialogState();
}

class _ImportDialogState extends State<_ImportDialog> {
  int selected = 0;
  final name = TextEditingController(text: 'Imported loadout');
  @override
  Widget build(BuildContext context) => AlertDialog(
    title: const Text('Preview loadouts'),
    content: SizedBox(
      width: 500,
      child: Column(
        mainAxisSize: MainAxisSize.min,
        children: [
          TextField(
            controller: name,
            decoration: const InputDecoration(labelText: 'Name'),
          ),
          const SizedBox(height: 12),
          RadioGroup<int>(
            groupValue: selected,
            onChanged: (v) => setState(() => selected = v!),
            child: Column(
              children: widget.options
                  .asMap()
                  .entries
                  .map(
                    (e) => RadioListTile<int>(
                      value: e.key,
                      title: Text(
                        '${e.value['name'] ?? 'Loadout ${e.key + 1}'}',
                      ),
                      subtitle: Text(
                        (e.value['loadout'] is Map ||
                                e.value['equipment'] is Map)
                            ? 'Equipment included'
                            : 'Preview available',
                      ),
                    ),
                  )
                  .toList(),
            ),
          ),
        ],
      ),
    ),
    actions: [
      TextButton(
        onPressed: () => Navigator.pop(context),
        child: const Text('Cancel'),
      ),
      FilledButton(
        onPressed: widget.options.isEmpty
            ? null
            : () {
                final x = {...widget.options[selected]};
                x['name'] = name.text.trim().isEmpty
                    ? 'Imported loadout'
                    : name.text.trim();
                Navigator.pop(context, x);
              },
        child: const Text('Use selected'),
      ),
    ],
  );
}

class _NumberField extends StatefulWidget {
  final String label;
  final int value;
  final ValueChanged<int> onChanged;
  final int min;
  final int max;
  final String? helper;

  const _NumberField({
    super.key,
    required this.label,
    required this.value,
    required this.onChanged,
    required this.min,
    required this.max,
    this.helper,
  });

  @override
  State<_NumberField> createState() => _NumberFieldState();
}

class _NumberFieldState extends State<_NumberField> {
  late final TextEditingController _controller;

  @override
  void initState() {
    super.initState();
    _controller = TextEditingController(text: '${widget.value}');
  }

  @override
  void didUpdateWidget(covariant _NumberField oldWidget) {
    super.didUpdateWidget(oldWidget);
    final text = '${widget.value}';
    if (oldWidget.value != widget.value && _controller.text != text) {
      _controller.value = _controller.value.copyWith(
        text: text,
        selection: TextSelection.collapsed(offset: text.length),
      );
    }
  }

  @override
  void dispose() {
    _controller.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) => TextField(
    controller: _controller,
    keyboardType: TextInputType.number,
    decoration: InputDecoration(
      labelText: widget.label,
      helperText: widget.helper,
    ),
    onSubmitted: (value) {
      final parsed = int.tryParse(value) ?? widget.value;
      widget.onChanged(parsed.clamp(widget.min, widget.max).toInt());
    },
  );
}

class _SmallListField extends StatefulWidget {
  final String label;
  final List<int> values;
  final ValueChanged<List<int>> update;

  const _SmallListField({
    super.key,
    required this.label,
    required this.values,
    required this.update,
  });

  @override
  State<_SmallListField> createState() => _SmallListFieldState();
}

class _SmallListFieldState extends State<_SmallListField> {
  late final TextEditingController _controller;

  String _text(List<int> values) => values.join(', ');

  @override
  void initState() {
    super.initState();
    _controller = TextEditingController(text: _text(widget.values));
  }

  @override
  void didUpdateWidget(covariant _SmallListField oldWidget) {
    super.didUpdateWidget(oldWidget);
    final text = _text(widget.values);
    if (oldWidget.values != widget.values && _controller.text != text) {
      _controller.value = _controller.value.copyWith(
        text: text,
        selection: TextSelection.collapsed(offset: text.length),
      );
    }
  }

  @override
  void dispose() {
    _controller.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) => SizedBox(
    width: 260,
    child: TextField(
      controller: _controller,
      keyboardType: TextInputType.number,
      decoration: InputDecoration(
        labelText: widget.label,
        helperText: 'Comma-separated ids',
      ),
      onSubmitted: (value) => widget.update(
        value
            .split(',')
            .map((x) => int.tryParse(x.trim()))
            .whereType<int>()
            .take(widget.label.startsWith('Prayer') ? 20 : 22)
            .toList(),
      ),
    ),
  );
}
