using System.Windows;
using System.Windows.Controls;
using System.Windows.Media;
using System.Text.RegularExpressions;
using System.Text.Json;
using Translator.Services;

namespace Translator
{
    public partial class MainWindow : Window
    {
        private bool _conversationStarted;
        private bool _stopRequested;
        private bool _synchronizingControls;
        private bool _restartInProgress;
        private readonly HashSet<string> _activeDirections = new(StringComparer.OrdinalIgnoreCase);
        private string? _pendingSourceText;
        private readonly LiveTranslatorBackend _backend = new();
        private static readonly Regex TranslationLine = new(
            @"^(?<language>[A-Z]{2})(?: \[low confidence\])?: (?<text>.+)$",
            RegexOptions.Compiled);

        public MainWindow()
        {
            InitializeComponent();

            StartTranslateButton.Click += SettingsButton_Click;
            BackButton.Click += BackButton_Click;
            ApplySettingsButton.Click += ApplySettingsButton_Click;
            ResetSettingsButton.Click += ResetSettingsButton_Click;
            StopTranslationButton.Click += StopTranslationButton_Click;
            QuickMyTranscriptCheckBox.Checked += QuickTranscriptCheckBox_Changed;
            QuickMyTranscriptCheckBox.Unchecked += QuickTranscriptCheckBox_Changed;
            QuickTheirTranscriptCheckBox.Checked += QuickTranscriptCheckBox_Changed;
            QuickTheirTranscriptCheckBox.Unchecked += QuickTranscriptCheckBox_Changed;
            QuickMyVoiceComboBox.SelectionChanged += QuickVoiceComboBox_SelectionChanged;
            QuickTheirVoiceComboBox.SelectionChanged += QuickVoiceComboBox_SelectionChanged;
            ConfidentialModeCheckBox.Checked += RuntimeSetting_Changed;
            ConfidentialModeCheckBox.Unchecked += RuntimeSetting_Changed;
            Closed += (_, _) => _backend.Dispose();

            _backend.OutputReceived += line => Dispatcher.Invoke(() => HandleBackendOutput(line));
            _backend.ErrorReceived += line => Dispatcher.Invoke(() => HandleBackendError(line));
            _backend.Exited += exitCode => Dispatcher.Invoke(() => HandleBackendExit(exitCode));

            ShowWelcome();
        }

        private void SettingsButton_Click(object sender, RoutedEventArgs e)
        {
            WelcomeView.Visibility = Visibility.Collapsed;
            ConversationView.Visibility = Visibility.Collapsed;
            SettingsView.Visibility = Visibility.Visible;
            SetSessionStatus("Configure translation", "#F59E0B");
        }

        private void BackButton_Click(object sender, RoutedEventArgs e)
        {
            if (_conversationStarted)
                ShowConversation();
            else
                ShowWelcome();
        }

        private async void ApplySettingsButton_Click(object sender, RoutedEventArgs e)
        {
            if (_backend.IsRunning)
            {
                _stopRequested = true;
                await _backend.StopAsync();
            }
            StartTranslationFromSettings();
        }

        private void ResetSettingsButton_Click(object sender, RoutedEventArgs e)
        {
            _synchronizingControls = true;
            try
            {
                MyLanguageComboBox.SelectedIndex = 0;
                MyTargetLanguageComboBox.SelectedIndex = 0;
                MyVoiceComboBox.SelectedIndex = 0;
                MyVoiceSpeedSlider.Value = 1.0;
                MyMicrophoneComboBox.SelectedIndex = 0;
                MyAudioOutputComboBox.SelectedIndex = 0;
                MeetingMicrophoneComboBox.SelectedIndex = 0;

                TheirLanguageComboBox.SelectedIndex = 0;
                TheirTargetLanguageComboBox.SelectedIndex = 0;
                TheirVoiceComboBox.SelectedIndex = 0;
                TheirVoiceSpeedSlider.Value = 1.0;
                TheirAudioSourceComboBox.SelectedIndex = 0;
                TheirAudioOutputComboBox.SelectedIndex = 0;

                MyTranscriptCheckBox.IsChecked = true;
                TheirTranscriptCheckBox.IsChecked = true;
                SpeakMyTranslationCheckBox.IsChecked = true;
                SpeakTheirTranslationCheckBox.IsChecked = true;
                CaptureDiagnosticsCheckBox.IsChecked = false;
                SessionProfileComboBox.SelectedIndex = 0;
                ConfidentialModeCheckBox.IsChecked = false;
            }
            finally
            {
                _synchronizingControls = false;
            }

            SetSessionStatus("Defaults restored · Apply to use", "#F59E0B");
        }

        private async void StopTranslationButton_Click(object sender, RoutedEventArgs e)
        {
            if (_backend.IsRunning)
            {
                _stopRequested = true;
                StopTranslationButton.IsEnabled = false;
                await _backend.StopAsync();
                StopTranslationButton.IsEnabled = true;
                StopTranslationButton.Content = "Resume translation";
                SetSessionStatus("Translation stopped", "#DC2626");
                return;
            }

            StartTranslationFromSettings();
        }

        private void StartTranslationFromSettings()
        {
            var source = SelectedText(MyLanguageComboBox);
            var target = SelectedText(MyTargetLanguageComboBox);
            var theirSource = SelectedText(TheirLanguageComboBox);
            var theirTarget = SelectedText(TheirTargetLanguageComboBox);
            var profile = (source, target) switch
            {
                ("English", "German") => "en-de",
                ("German", "English") => "de-en",
                _ => null,
            };

            var theirSourceCode = LanguageCode(theirSource);
            var theirTargetCode = LanguageCode(theirTarget);
            if (profile is null || theirSourceCode is null || theirTargetCode is null)
            {
                MessageBox.Show(
                    "The current translator supports English and German conversation directions only.",
                    "Unsupported translation direction",
                    MessageBoxButton.OK,
                    MessageBoxImage.Information);
                return;
            }

            var outboundVoice = SelectedVoice(MyVoiceComboBox);
            var inboundVoice = SelectedVoice(TheirVoiceComboBox);
            var confidential = ConfidentialModeCheckBox.IsChecked == true;
            var diagnostics = !confidential && CaptureDiagnosticsCheckBox.IsChecked == true;

            try
            {
                _stopRequested = false;
                _pendingSourceText = null;
                _activeDirections.Clear();
                SynchronizeConversationControls();
                _backend.Start(new BackendStartOptions(
                    profile,
                    theirSourceCode,
                    theirTargetCode,
                    outboundVoice,
                    inboundVoice,
                    MyVoiceSpeedSlider.Value,
                    TheirVoiceSpeedSlider.Value,
                    confidential,
                    diagnostics));
                _conversationStarted = true;
                ConversationDirectionText.Text =
                    $"You: {source} → {target} · Others: {theirSource} → {theirTarget}";
                SessionDirectionText.Text =
                    $"{source} → {target} · {theirSource} → {theirTarget}";
                StopTranslationButton.Content = "Stop translation";
                ShowConversation();
                SetSessionStatus("Starting translation", "#F59E0B");
            }
            catch (Exception exception)
            {
                SetSessionStatus("Translator unavailable", "#DC2626");
                MessageBox.Show(
                    exception.Message,
                    "Live Translator could not start",
                    MessageBoxButton.OK,
                    MessageBoxImage.Error);
            }
        }

        private void ShowWelcome()
        {
            WelcomeView.Visibility = Visibility.Visible;
            SettingsView.Visibility = Visibility.Collapsed;
            ConversationView.Visibility = Visibility.Collapsed;
            SetSessionStatus("Ready to set up", "#0BDA51");
        }

        private void ShowConversation()
        {
            WelcomeView.Visibility = Visibility.Collapsed;
            SettingsView.Visibility = Visibility.Collapsed;
            ConversationView.Visibility = Visibility.Visible;
            UpdateTranscriptVisibility();
            SetSessionStatus("Ready to translate", "#0BDA51");
        }

        private void SynchronizeConversationControls()
        {
            _synchronizingControls = true;
            QuickMyVoiceComboBox.SelectedIndex = MyVoiceComboBox.SelectedIndex;
            QuickTheirVoiceComboBox.SelectedIndex = TheirVoiceComboBox.SelectedIndex;
            QuickMyTranscriptCheckBox.IsChecked = MyTranscriptCheckBox.IsChecked;
            QuickTheirTranscriptCheckBox.IsChecked = TheirTranscriptCheckBox.IsChecked;
            _synchronizingControls = false;
        }

        private void UpdateTranscriptVisibility()
        {
            MyFirstTranscript.Visibility = QuickMyTranscriptCheckBox.IsChecked == true
                ? Visibility.Visible
                : Visibility.Collapsed;
            MySecondTranscript.Visibility = Visibility.Collapsed;
            TheirTranscript.Visibility = QuickTheirTranscriptCheckBox.IsChecked == true
                ? Visibility.Visible
                : Visibility.Collapsed;
            TranscriptPanel.Visibility = QuickMyTranscriptCheckBox.IsChecked == true ||
                                         QuickTheirTranscriptCheckBox.IsChecked == true
                ? Visibility.Visible
                : Visibility.Collapsed;
            HiddenTranscriptsView.Visibility = TranscriptPanel.Visibility == Visibility.Visible
                ? Visibility.Collapsed
                : Visibility.Visible;
        }

        private void QuickTranscriptCheckBox_Changed(object sender, RoutedEventArgs e)
        {
            if (_synchronizingControls)
                return;

            UpdateTranscriptVisibility();
        }

        private async void QuickVoiceComboBox_SelectionChanged(
            object sender,
            SelectionChangedEventArgs e)
        {
            if (_synchronizingControls)
                return;

            _synchronizingControls = true;
            if (ReferenceEquals(sender, QuickMyVoiceComboBox))
                MyVoiceComboBox.SelectedIndex = QuickMyVoiceComboBox.SelectedIndex;
            else
                TheirVoiceComboBox.SelectedIndex = QuickTheirVoiceComboBox.SelectedIndex;
            _synchronizingControls = false;

            await RestartForRuntimeSettingAsync("Applying voice");
        }

        private async void RuntimeSetting_Changed(object sender, RoutedEventArgs e)
        {
            if (_synchronizingControls)
                return;

            await RestartForRuntimeSettingAsync("Applying privacy setting");
        }

        private async Task RestartForRuntimeSettingAsync(string status)
        {
            if (!_conversationStarted || !_backend.IsRunning || _restartInProgress)
                return;

            _restartInProgress = true;
            try
            {
                SetSessionStatus(status, "#F59E0B");
                _stopRequested = true;
                await _backend.StopAsync();
                await Task.Delay(750);
                StartTranslationFromSettings();
            }
            finally
            {
                _restartInProgress = false;
            }
        }

        private void SetSessionStatus(string text, string dotColor)
        {
            SessionStatusText.Text = text;
            SessionStatusDot.Fill = (Brush)new BrushConverter().ConvertFromString(dotColor)!;
        }

        private void HandleBackendOutput(string line)
        {
            if (TryHandleBackendEvent(line))
                return;

            var match = TranslationLine.Match(line);
            if (!match.Success)
                return;

            if (_pendingSourceText is null)
            {
                _pendingSourceText = match.Groups["text"].Value;
                LatestSourceText.Text = _pendingSourceText;
                return;
            }

            LatestTranslationLabel.Text = $"TRANSLATION · {match.Groups["language"].Value}";
            LatestTranslationText.Text = match.Groups["text"].Value;
            _pendingSourceText = null;
        }

        private bool TryHandleBackendEvent(string line)
        {
            if (!line.StartsWith('{'))
                return false;

            try
            {
                using var document = JsonDocument.Parse(line);
                var root = document.RootElement;
                if (!root.TryGetProperty("type", out var type))
                    return false;

                if (type.GetString() == "status" &&
                    root.TryGetProperty("state", out var state) &&
                    state.GetString() == "active")
                {
                    var confidential = root.TryGetProperty("confidential", out var confidentialElement) &&
                                       confidentialElement.ValueKind == JsonValueKind.True;
                    if (root.TryGetProperty("role", out var statusRoleElement) &&
                        statusRoleElement.GetString() is { Length: > 0 } statusRole)
                        _activeDirections.Add(statusRole);

                    if (_activeDirections.Contains("outbound") &&
                        _activeDirections.Contains("inbound"))
                    {
                        SetSessionStatus(
                            confidential ? "Confidential translation active" : "Translation active",
                            "#0BDA51");
                    }
                    else
                    {
                        SetSessionStatus("Starting translation", "#F59E0B");
                    }
                    return true;
                }

                if (type.GetString() != "translation")
                    return false;

                var sourceText = root.GetProperty("source_text").GetString() ?? string.Empty;
                var translatedText = root.GetProperty("translated_text").GetString() ?? string.Empty;
                var targetLanguage = root.GetProperty("target_language").GetString() ?? string.Empty;
                var role = root.TryGetProperty("role", out var roleElement)
                    ? roleElement.GetString()
                    : "outbound";

                if (role == "inbound")
                {
                    LatestTheirSourceText.Text = sourceText;
                    LatestTheirTranslationText.Text = translatedText;
                    LatestTheirTranslationLabel.Text =
                        $"TRANSLATION · {targetLanguage.ToUpperInvariant()}";
                }
                else
                {
                    LatestSourceText.Text = sourceText;
                    LatestTranslationText.Text = translatedText;
                    LatestTranslationLabel.Text =
                        $"TRANSLATION · {targetLanguage.ToUpperInvariant()}";
                }
                _pendingSourceText = null;
                return true;
            }
            catch (JsonException)
            {
                return false;
            }
        }

        private void HandleBackendError(string line)
        {
            if (_stopRequested ||
                !line.StartsWith("Error:", StringComparison.OrdinalIgnoreCase))
                return;

            SetSessionStatus("Translation error", "#DC2626");
            LatestTranslationText.Text = line;
        }

        private void HandleBackendExit(int exitCode)
        {
            if (_stopRequested)
                return;

            StopTranslationButton.Content = "Resume translation";
            SetSessionStatus(
                exitCode == 0 ? "Translation ended" : "Translation stopped with an error",
                "#DC2626");
        }

        private static string SelectedText(ComboBox comboBox) =>
            (comboBox.SelectedItem as ComboBoxItem)?.Content?.ToString() ?? string.Empty;

        private static string? SelectedVoice(ComboBox comboBox)
        {
            var selected = SelectedText(comboBox);
            if (selected.Contains("Female", StringComparison.OrdinalIgnoreCase))
                return "female";
            if (selected.Contains("Male", StringComparison.OrdinalIgnoreCase))
                return "male";
            return null;
        }

        private static string? LanguageCode(string language) => language switch
        {
            "English" => "en",
            "German" => "de",
            _ => null,
        };
    }
}
