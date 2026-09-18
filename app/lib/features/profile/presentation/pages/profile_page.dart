    this.onDelete,
    this.error,
  });

  final UserPreferences? preferences;
  final bool busy;
  final String? error;
  final Future<void> Function() onReload;
  final Future<void> Function(UserPreferences) onSave;
  final Future<void> Function()? onDelete;

  @override
  State<ProfilePreferencesForm> createState() => _ProfilePreferencesFormState();
}

class _ProfilePreferencesFormState extends State<ProfilePreferencesForm> {
  final _formKey = GlobalKey<FormState>();
  late final TextEditingController _horizonController = TextEditingController();
  late final TextEditingController _currencyController = TextEditingController();
  late final TextEditingController _drawdownController = TextEditingController();
  late final TextEditingController _capitalController = TextEditingController();
  late String _riskTolerance;
  late String _objective;
  late String? _experienceLevel;
  late String? _liquidityNeed;

  @override
  void initState() {
    super.initState();
    _sync(widget.preferences);
  }

  @override
  void didUpdateWidget(covariant ProfilePreferencesForm oldWidget) {
    super.didUpdateWidget(oldWidget);
    if (oldWidget.preferences != widget.preferences) {
      _sync(widget.preferences);
    }
  }

  void _sync(UserPreferences? preferences) {
    final value = preferences ?? UserPreferences.defaults();
    _riskTolerance = value.riskTolerance;
    _objective = value.objective;
    _experienceLevel = value.experienceLevel;
    _liquidityNeed = value.liquidityNeed;
     _horizonController.text = value.investmentHorizonYears.toString();
    _currencyController.text = value.baseCurrency;
    _drawdownController.text = value.maxDrawdownTolerancePct?.toString() ?? '';
    _capitalController.text = value.availableCapital?.toString() ?? '';
  }

  @override
  void dispose() {
    _horizonController.dispose();
    _currencyController.dispose();
    _drawdownController.dispose();
    _capitalController.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return Form(
      key: _formKey,
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,