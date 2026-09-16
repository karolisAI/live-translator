using System.Diagnostics;
using System.Globalization;
using System.IO;

namespace Translator.Services;

internal sealed record BackendStartOptions(
    string OutboundProfile,
    string TheirLanguage,
    string InboundTargetLanguage,
    string? OutboundVoice,
    string? InboundVoice,
    double OutboundVoiceSpeed,
    double InboundVoiceSpeed,
    bool Confidential,
    bool Diagnostics);

internal sealed class LiveTranslatorBackend : IDisposable
{
    private Process? _process;
    private Process? _stoppingProcess;

    public event Action<string>? OutputReceived;
    public event Action<string>? ErrorReceived;
    public event Action<int>? Exited;

    public bool IsRunning => _process is { HasExited: false };

    public void Start(BackendStartOptions options)
    {
        if (IsRunning)
            throw new InvalidOperationException("A translation session is already running.");

        var startInfo = CreateStartInfo();
        startInfo.ArgumentList.Add("converse");
        startInfo.ArgumentList.Add("--outbound-profile");
        startInfo.ArgumentList.Add(options.OutboundProfile);
        startInfo.ArgumentList.Add("--their-language");
        startInfo.ArgumentList.Add(options.TheirLanguage);
        startInfo.ArgumentList.Add("--inbound-target-language");
        startInfo.ArgumentList.Add(options.InboundTargetLanguage);
        startInfo.ArgumentList.Add("--event-format");
        startInfo.ArgumentList.Add("jsonl");

        AddOptionalArgument(startInfo, "--outbound-voice", options.OutboundVoice);
        AddOptionalArgument(startInfo, "--inbound-voice", options.InboundVoice);
        startInfo.ArgumentList.Add("--outbound-voice-speed");
        startInfo.ArgumentList.Add(options.OutboundVoiceSpeed.ToString("0.0", CultureInfo.InvariantCulture));
        startInfo.ArgumentList.Add("--inbound-voice-speed");
        startInfo.ArgumentList.Add(options.InboundVoiceSpeed.ToString("0.0", CultureInfo.InvariantCulture));

        if (options.Confidential)
            startInfo.ArgumentList.Add("--confidential");
        else if (options.Diagnostics)
            startInfo.ArgumentList.Add("--diagnostics");

        var process = new Process
        {
            StartInfo = startInfo,
            EnableRaisingEvents = true,
        };
        process.OutputDataReceived += (_, args) =>
        {
            if (!ReferenceEquals(_stoppingProcess, process) &&
                !string.IsNullOrWhiteSpace(args.Data))
                OutputReceived?.Invoke(args.Data);
        };
        process.ErrorDataReceived += (_, args) =>
        {
            if (!ReferenceEquals(_stoppingProcess, process) &&
                !string.IsNullOrWhiteSpace(args.Data))
                ErrorReceived?.Invoke(args.Data);
        };
        process.Exited += (_, _) =>
        {
            var wasStopped = ReferenceEquals(_stoppingProcess, process);
            if (ReferenceEquals(_process, process))
                _process = null;
            if (!wasStopped)
                Exited?.Invoke(process.ExitCode);
        };

        if (!process.Start())
            throw new InvalidOperationException("Live Translator backend could not be started.");

        _process = process;
        process.BeginOutputReadLine();
        process.BeginErrorReadLine();
    }

    public async Task StopAsync()
    {
        var process = _process;
        if (process is null || process.HasExited)
            return;

        _stoppingProcess = process;
        _process = null;
        try
        {
            process.EnableRaisingEvents = false;
            // The current CLI has no control channel yet. Terminating the process
            // is an MVP bridge; replace this with a graceful stop command when the
            // backend protocol is added.
            process.Kill(entireProcessTree: true);
            await process.WaitForExitAsync();
        }
        finally
        {
            process.Dispose();
            if (ReferenceEquals(_stoppingProcess, process))
                _stoppingProcess = null;
        }
    }

    public void Dispose()
    {
        if (_process is { HasExited: false } process)
            process.Kill(entireProcessTree: true);
        _process?.Dispose();
    }

    private static ProcessStartInfo CreateStartInfo()
    {
        var configuredPath = Environment.GetEnvironmentVariable("LIVE_TRANSLATOR_BACKEND");
        if (!string.IsNullOrWhiteSpace(configuredPath))
            return ForExecutable(configuredPath);

        var adjacent = Path.Combine(AppContext.BaseDirectory, "LiveTranslator.exe");
        if (File.Exists(adjacent))
            return ForExecutable(adjacent);

        var installed = Path.Combine(
            Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),
            "Programs",
            "LiveTranslator",
            "LiveTranslator.exe");
        if (File.Exists(installed))
            return ForExecutable(installed);

        var repository = FindRepositoryRoot();
        if (repository is not null)
        {
            var development = ForExecutable("uv");
            development.WorkingDirectory = repository;
            development.ArgumentList.Add("run");
            development.ArgumentList.Add("--frozen");
            development.ArgumentList.Add("live-translator");
            return development;
        }

        throw new FileNotFoundException(
            "LiveTranslator.exe was not found. Install Live Translator, place " +
            "LiveTranslator.exe next to Translator.exe, or set LIVE_TRANSLATOR_BACKEND.");
    }

    private static ProcessStartInfo ForExecutable(string executable) => new()
    {
        FileName = executable,
        UseShellExecute = false,
        RedirectStandardOutput = true,
        RedirectStandardError = true,
        CreateNoWindow = true,
        StandardOutputEncoding = System.Text.Encoding.UTF8,
        StandardErrorEncoding = System.Text.Encoding.UTF8,
        Environment = { ["PYTHONUNBUFFERED"] = "1" },
    };

    private static void AddOptionalArgument(
        ProcessStartInfo startInfo,
        string name,
        string? value)
    {
        if (string.IsNullOrWhiteSpace(value))
            return;

        startInfo.ArgumentList.Add(name);
        startInfo.ArgumentList.Add(value);
    }

    private static string? FindRepositoryRoot()
    {
        var directory = new DirectoryInfo(AppContext.BaseDirectory);
        while (directory is not null)
        {
            if (File.Exists(Path.Combine(directory.FullName, "pyproject.toml")))
                return directory.FullName;
            directory = directory.Parent;
        }
        return null;
    }
}
