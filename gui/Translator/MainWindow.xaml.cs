using System.Windows;
using System.Windows.Controls;
using System.Windows.Media;
using System.Text.Json;
using System.IO;
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
        private readonly LiveTranslatorBackend _backend = new();
        private static readonly string SettingsPath = Path.Combine(
            Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),
            "LiveTranslator",
            "gui-settings.json");

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
            MyLanguageComboBox.SelectionChanged += LanguageComboBox_SelectionChanged;
            MyTargetLanguageComboBox.SelectionChanged += LanguageComboBox_SelectionChanged;
            TheirLanguageComboBox.SelectionChanged += LanguageComboBox_SelectionChanged;
            TheirTargetLanguageComboBox.SelectionChanged += LanguageComboBox_SelectionChanged;
            MyVoiceSpeedSlider.ValueChanged += VoiceSpeedSlider_ValueChanged;
            TheirVoiceSpeedSlider.ValueChanged += VoiceSpeedSlider_ValueChanged;
            ConfidentialModeCheckBox.Checked += RuntimeSetting_Changed;
            ConfidentialModeCheckBox.Unchecked += RuntimeSetting_Changed;
            CaptureDiagnosticsCheckBox.Checked += CaptureDiagnosticsCheckBox_Checked;
            Loaded += MainWindow_Loaded;
            Closed += (_, _) =>
            {
                SaveSettings();
                _backend.Dispose();
            };

            _backend.OutputReceived += line => Dispatcher.Invoke(() => HandleBackendOutput(line));
            _backend.ErrorReceived += line => Dispatcher.Invoke(() => HandleBackendError(line));
            _backend.Exited += exitCode => Dispatcher.Invoke(() => HandleBackendExit(exitCode));

            ShowWelcome();
        }

        private async void MainWindow_Loaded(object sender, RoutedEventArgs e)
        {
            try
            {
                var devices = await LiveTranslatorBackend.ListDevicesAsync();
                PopulateDevices(MyMicrophoneComboBox, devices.Inputs);
                PopulateDevices(MeetingMicrophoneComboBox, devices.Inputs);
                PopulateDevices(TheirAudioSourceComboBox, devices.Inputs);
                PopulateDevices(MyAudioOutputComboBox, devices.Outputs);
                PopulateDevices(TheirAudioOutputComboBox, devices.Outputs);
            }
            catch (Exception exception)
            {
                SetSessionStatus("Audio devices unavailable · Automatic routing will be used", "#F59E0B");
                System.Diagnostics.Debug.WriteLine(exception);
            }
            finally
            {
                LoadSettings();
                UpdateVoiceSpeedLabels();
            }
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
            SaveSettings();
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
                ConfidentialModeCheckBox.IsChecked = false;
            }
            finally
            {
                _synchronizingControls = false;
            }

            SynchronizeConversationControls();
            UpdateVoiceSpeedLabels();
            SaveSettings();
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
                    SelectedDeviceKey(MyMicrophoneComboBox),
                    SelectedDeviceKey(MyAudioOutputComboBox),
                    SelectedDeviceKey(MeetingMicrophoneComboBox),
                    SelectedDeviceKey(TheirAudioSourceComboBox),
                    SelectedDeviceKey(TheirAudioOutputComboBox),
                    SpeakMyTranslationCheckBox.IsChecked == true,
                    SpeakTheirTranslationCheckBox.IsChecked == true,
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

            _synchronizingControls = true;
            MyTranscriptCheckBox.IsChecked = QuickMyTranscriptCheckBox.IsChecked;
            TheirTranscriptCheckBox.IsChecked = QuickTheirTranscriptCheckBox.IsChecked;
            _synchronizingControls = false;
            UpdateTranscriptVisibility();
            SaveSettings();
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

            SaveSettings();
            await RestartForRuntimeSettingAsync("Applying voice");
        }

        private async void RuntimeSetting_Changed(object sender, RoutedEventArgs e)
        {
            if (_synchronizingControls)
                return;

            if (ConfidentialModeCheckBox.IsChecked == true)
                CaptureDiagnosticsCheckBox.IsChecked = false;
            SaveSettings();
            await RestartForRuntimeSettingAsync("Applying privacy setting");
        }

        private void CaptureDiagnosticsCheckBox_Checked(object sender, RoutedEventArgs e)
        {
            if (_synchronizingControls || ConfidentialModeCheckBox.IsChecked != true)
                return;

            _synchronizingControls = true;
            ConfidentialModeCheckBox.IsChecked = false;
            _synchronizingControls = false;
        }

        private void VoiceSpeedSlider_ValueChanged(
            object sender,
            RoutedPropertyChangedEventArgs<double> e) => UpdateVoiceSpeedLabels();

        private void LanguageComboBox_SelectionChanged(object sender, SelectionChangedEventArgs e)
        {
            if (_synchronizingControls)
                return;

            _synchronizingControls = true;
            if (ReferenceEquals(sender, MyLanguageComboBox) &&
                SelectedText(MyLanguageComboBox) == SelectedText(MyTargetLanguageComboBox))
                MyTargetLanguageComboBox.SelectedIndex = MyLanguageComboBox.SelectedIndex;
            else if (ReferenceEquals(sender, MyTargetLanguageComboBox) &&
                     SelectedText(MyTargetLanguageComboBox) == SelectedText(MyLanguageComboBox))
                MyLanguageComboBox.SelectedIndex = MyTargetLanguageComboBox.SelectedIndex;
            else if (ReferenceEquals(sender, TheirLanguageComboBox) &&
                     SelectedText(TheirLanguageComboBox) == SelectedText(TheirTargetLanguageComboBox))
                TheirTargetLanguageComboBox.SelectedIndex = TheirLanguageComboBox.SelectedIndex;
            else if (ReferenceEquals(sender, TheirTargetLanguageComboBox) &&
                     SelectedText(TheirTargetLanguageComboBox) == SelectedText(TheirLanguageComboBox))
                TheirLanguageComboBox.SelectedIndex = TheirTargetLanguageComboBox.SelectedIndex;
            _synchronizingControls = false;
        }

        private void UpdateVoiceSpeedLabels()
        {
            MyVoiceSpeedText.Text = $"{MyVoiceSpeedSlider.Value:0.0}×";
            TheirVoiceSpeedText.Text = $"{TheirVoiceSpeedSlider.Value:0.0}×";
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
            TryHandleBackendEvent(line);
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

                if (type.GetString() is "error" or "warning")
                {
                    var message = root.TryGetProperty("message", out var messageElement)
                        ? messageElement.GetString() ?? "Backend reported a problem."
                        : "Backend reported a problem.";
                    var isError = type.GetString() == "error";
                    SetSessionStatus(
                        isError ? "Translation error" : "Translation warning",
                        isError ? "#DC2626" : "#F59E0B");
                    LatestTranslationText.Text = message;
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
                return true;
            }
            catch (JsonException)
            {
                return false;
            }
        }

        private void HandleBackendError(string line)
        {
            if (_stopRequested)
                return;

            var isWarning = line.StartsWith("Warning:", StringComparison.OrdinalIgnoreCase);
            SetSessionStatus(
                isWarning ? "Translation warning" : "Translation error",
                isWarning ? "#F59E0B" : "#DC2626");
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

        private static string? SelectedDevice(ComboBox comboBox)
        {
            return (comboBox.SelectedItem as ComboBoxItem)?.Tag is AudioDeviceOption device
                ? device.PersistenceKey
                : null;
        }

        private static void PopulateDevices(
            ComboBox comboBox,
            IReadOnlyList<AudioDeviceOption> devices)
        {
            while (comboBox.Items.Count > 1)
                comboBox.Items.RemoveAt(1);

            foreach (var device in devices)
            {
                comboBox.Items.Add(new ComboBoxItem
                {
                    Content = string.IsNullOrWhiteSpace(device.HostApi)
                        ? device.Name
                        : $"{device.Name} · {device.HostApi}",
                    Tag = device,
                    ToolTip = $"Device {device.Id}: {device.Name}",
                });
            }
            comboBox.SelectedIndex = 0;
        }

        private void SaveSettings()
        {
            try
            {
                var settings = new GuiSettings(
                    MyLanguageComboBox.SelectedIndex,
                    MyTargetLanguageComboBox.SelectedIndex,
                    MyVoiceComboBox.SelectedIndex,
                    MyVoiceSpeedSlider.Value,
                    SelectedDevice(MyMicrophoneComboBox),
                    SelectedDevice(MyAudioOutputComboBox),
                    SelectedDevice(MeetingMicrophoneComboBox),
                    TheirLanguageComboBox.SelectedIndex,
                    TheirTargetLanguageComboBox.SelectedIndex,
                    TheirVoiceComboBox.SelectedIndex,
                    TheirVoiceSpeedSlider.Value,
                    SelectedDevice(TheirAudioSourceComboBox),
                    SelectedDevice(TheirAudioOutputComboBox),
                    MyTranscriptCheckBox.IsChecked == true,
                    TheirTranscriptCheckBox.IsChecked == true,
                    SpeakMyTranslationCheckBox.IsChecked == true,
                    SpeakTheirTranslationCheckBox.IsChecked == true,
                    CaptureDiagnosticsCheckBox.IsChecked == true,
                    ConfidentialModeCheckBox.IsChecked == true);

                Directory.CreateDirectory(Path.GetDirectoryName(SettingsPath)!);
                File.WriteAllText(
                    SettingsPath,
                    JsonSerializer.Serialize(settings, new JsonSerializerOptions { WriteIndented = true }));
            }
            catch (Exception exception)
            {
                System.Diagnostics.Debug.WriteLine(exception);
            }
        }

        private void LoadSettings()
        {
            if (!File.Exists(SettingsPath))
                return;

            try
            {
                var settings = JsonSerializer.Deserialize<GuiSettings>(File.ReadAllText(SettingsPath));
                if (settings is null)
                    return;

                _synchronizingControls = true;
                SelectIndex(MyLanguageComboBox, settings.MyLanguageIndex);
                SelectIndex(MyTargetLanguageComboBox, settings.MyTargetLanguageIndex);
                SelectIndex(MyVoiceComboBox, settings.MyVoiceIndex);
                MyVoiceSpeedSlider.Value = settings.MyVoiceSpeed;
                SelectDevice(MyMicrophoneComboBox, settings.MyMicrophoneDevice);
                SelectDevice(MyAudioOutputComboBox, settings.MyAudioOutputDevice);
                SelectDevice(MeetingMicrophoneComboBox, settings.MeetingMicrophoneDevice);

                SelectIndex(TheirLanguageComboBox, settings.TheirLanguageIndex);
                SelectIndex(TheirTargetLanguageComboBox, settings.TheirTargetLanguageIndex);
                SelectIndex(TheirVoiceComboBox, settings.TheirVoiceIndex);
                TheirVoiceSpeedSlider.Value = settings.TheirVoiceSpeed;
                SelectDevice(TheirAudioSourceComboBox, settings.TheirAudioSourceDevice);
                SelectDevice(TheirAudioOutputComboBox, settings.TheirAudioOutputDevice);

                MyTranscriptCheckBox.IsChecked = settings.ShowMyTranscript;
                TheirTranscriptCheckBox.IsChecked = settings.ShowTheirTranscript;
                SpeakMyTranslationCheckBox.IsChecked = settings.SpeakMyTranslation;
                SpeakTheirTranslationCheckBox.IsChecked = settings.SpeakTheirTranslation;
                CaptureDiagnosticsCheckBox.IsChecked = settings.CaptureDiagnostics;
                ConfidentialModeCheckBox.IsChecked = settings.Confidential;
                if (ConfidentialModeCheckBox.IsChecked == true)
                    CaptureDiagnosticsCheckBox.IsChecked = false;
                SynchronizeConversationControls();
            }
            catch (Exception exception)
            {
                System.Diagnostics.Debug.WriteLine(exception);
            }
            finally
            {
                _synchronizingControls = false;
            }
        }

        private static void SelectIndex(ComboBox comboBox, int selectedIndex)
        {
            comboBox.SelectedIndex = selectedIndex >= 0 && selectedIndex < comboBox.Items.Count
                ? selectedIndex
                : 0;
        }

        private static void SelectDevice(ComboBox comboBox, string? deviceId)
        {
            if (!string.IsNullOrWhiteSpace(deviceId))
            {
                foreach (var item in comboBox.Items.OfType<ComboBoxItem>())
                {
                    var device = item.Tag as AudioDeviceOption;
                    if ((device is not null &&
                         (string.Equals(device.PersistenceKey, deviceId, StringComparison.Ordinal) ||
                          string.Equals(device.Id, deviceId, StringComparison.Ordinal))) ||
                        string.Equals(item.Content?.ToString(), deviceId, StringComparison.Ordinal))
                    {
                        comboBox.SelectedItem = item;
                        return;
                    }
                }
            }
            comboBox.SelectedIndex = 0;
        }

        private static string? SelectedDeviceKey(ComboBox comboBox)
        {
            return (comboBox.SelectedItem as ComboBoxItem)?.Tag is AudioDeviceOption device
                ? device.Id
                : null;
        }

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

        private sealed record GuiSettings(
            int MyLanguageIndex,
            int MyTargetLanguageIndex,
            int MyVoiceIndex,
            double MyVoiceSpeed,
            string? MyMicrophoneDevice,
            string? MyAudioOutputDevice,
            string? MeetingMicrophoneDevice,
            int TheirLanguageIndex,
            int TheirTargetLanguageIndex,
            int TheirVoiceIndex,
            double TheirVoiceSpeed,
            string? TheirAudioSourceDevice,
            string? TheirAudioOutputDevice,
            bool ShowMyTranscript,
            bool ShowTheirTranscript,
            bool SpeakMyTranslation,
            bool SpeakTheirTranslation,
            bool CaptureDiagnostics,
            bool Confidential);
    }
}
