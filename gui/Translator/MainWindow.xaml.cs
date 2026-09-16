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
            StopTranslationButton.Click += StopTranslationButton_Click;
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

        private void ApplySettingsButton_Click(object sender, RoutedEventArgs e)
        {
            StartTranslationFromSettings();
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
                SetSessionStatus("Translation stopped", "#94A3B8");
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

            var showText = MyTranscriptCheckBox.IsChecked == true ||
                           TheirTranscriptCheckBox.IsChecked == true;

            try
            {
                _stopRequested = false;
                _pendingSourceText = null;
                _backend.Start(new BackendStartOptions(
                    profile,
                    theirSourceCode,
                    theirTargetCode,
                    showText));
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
            MyFirstTranscript.Visibility = MyTranscriptCheckBox.IsChecked == true
                ? Visibility.Visible
                : Visibility.Collapsed;
            MySecondTranscript.Visibility = Visibility.Collapsed;
            TheirTranscript.Visibility = TheirTranscriptCheckBox.IsChecked == true
                ? Visibility.Visible
                : Visibility.Collapsed;
            TranscriptPanel.Visibility = MyTranscriptCheckBox.IsChecked == true ||
                                         TheirTranscriptCheckBox.IsChecked == true
                ? Visibility.Visible
                : Visibility.Collapsed;
            HiddenTranscriptsView.Visibility = TranscriptPanel.Visibility == Visibility.Visible
                ? Visibility.Collapsed
                : Visibility.Visible;
            SetSessionStatus("Ready to translate", "#0BDA51");
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
                    SetSessionStatus("Translation active", "#0BDA51");
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
                exitCode == 0 ? "#94A3B8" : "#DC2626");
        }

        private static string SelectedText(ComboBox comboBox) =>
            (comboBox.SelectedItem as ComboBoxItem)?.Content?.ToString() ?? string.Empty;

        private static string? LanguageCode(string language) => language switch
        {
            "English" => "en",
            "German" => "de",
            _ => null,
        };
    }
}
