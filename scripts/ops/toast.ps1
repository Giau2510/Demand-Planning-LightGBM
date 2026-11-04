<#
.SYNOPSIS  Windows toast notification (owner rule 03/11: notify when a big step ends, on errors, stops and when the owner
           is needed). Built-in WinRT API only, nothing installed. ASCII only; the texts come as arguments.
.EXAMPLE   powershell -NoProfile -ExecutionPolicy Bypass -File scripts\ops\toast.ps1 -Title "Demand Forecast" -Text "E2 done"
#>
param([Parameter(Mandatory = $true)][string]$Title, [Parameter(Mandatory = $true)][string]$Text)
$ErrorActionPreference = "Stop"
try {
    [Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType = WindowsRuntime] | Out-Null
    $xml = [Windows.UI.Notifications.ToastNotificationManager]::GetTemplateContent([Windows.UI.Notifications.ToastTemplateType]::ToastText02)
    $nodes = $xml.GetElementsByTagName("text")
    [void]$nodes.Item(0).AppendChild($xml.CreateTextNode($Title))
    [void]$nodes.Item(1).AppendChild($xml.CreateTextNode($Text))
    $toast = [Windows.UI.Notifications.ToastNotification]::new($xml)
    # the AppUserModelID of Windows PowerShell: always registered, so the toast is shown without installing anything
    $app = '{1AC14E77-02E7-4E5D-B744-2EB1AE5198B7}\WindowsPowerShell\v1.0\powershell.exe'
    [Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier($app).Show($toast)
    exit 0
} catch {
    Write-Host "toast failed: $($_.Exception.Message)"
    exit 1
}
