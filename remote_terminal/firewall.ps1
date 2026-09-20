<#
.SYNOPSIS
  Brain Terminal - Windows Firewall Whitelist Hardening
.DESCRIPTION
  Default-block mode. Only allows WireGuard, Web, DNS, NTP, Model APIs.
  All other inbound/outbound traffic BLOCKED.
  Run as Administrator.
#>
#Requires -RunAsAdministrator

param(
    [Parameter(Mandatory = $true)]
    [string]$RelayIp,
    [Parameter(Mandatory = $true)]
    [string]$TunnelCidr,
    [int]$RelayPort = 443,
    [int]$WireGuardPort = 51432
)

$ErrorActionPreference = "Stop"
$RELAY_IP = $RelayIp
$RELAY_PORT = $RelayPort
$WG_PORT = $WireGuardPort
$TUNNEL = $TunnelCidr
Write-Host "========================================" -ForegroundColor Cyan
Write-Host "  Brain Terminal Firewall Hardening" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan

# Step 1 - Backup
Write-Host "[1/5] Backing up current rules..." -ForegroundColor Yellow
$backupFile = "$env:USERPROFILE\Desktop\firewall-backup-$(Get-Date -Format 'yyyyMMdd-HHmmss').wfw"
netsh advfirewall export $backupFile 2>&1 | Out-Null
Write-Host "  Backup saved: $backupFile" -ForegroundColor Green

# Step 2 - Default block
Write-Host "[2/5] Setting default policy: Block inbound, Block outbound..." -ForegroundColor Yellow
Set-NetFirewallProfile -Profile Domain,Private,Public -DefaultInboundAction Block -DefaultOutboundAction Block
Write-Host "  Default policy: BLOCK" -ForegroundColor Green

# Step 3 - Whitelist rules
Write-Host "[3/5] Creating whitelist rules..." -ForegroundColor Yellow

# Inbound
New-NetFirewallRule -DisplayName "WG: WireGuard Listen" -Direction Inbound -Protocol UDP -LocalPort $WG_PORT -Action Allow -Profile Any -Description "Local WireGuard listen port" | Out-Null
Write-Host "  In: WireGuard UDP $WG_PORT" -ForegroundColor Green

New-NetFirewallRule -DisplayName "WG: Tunnel Subnet" -Direction Inbound -RemoteAddress $TUNNEL -Action Allow -Profile Any -Description "WireGuard tunnel subnet" | Out-Null
Write-Host "  In: Tunnel $TUNNEL" -ForegroundColor Green

# Loopback
New-NetFirewallRule -DisplayName "System: Loopback" -Direction Inbound -RemoteAddress 127.0.0.1,::1 -Action Allow -Profile Any | Out-Null
Write-Host "  In: Loopback" -ForegroundColor Green

# Outbound - WireGuard to relay
New-NetFirewallRule -DisplayName "WG: Relay Connect" -Direction Outbound -Protocol UDP -RemoteAddress $RELAY_IP -RemotePort $RELAY_PORT -Action Allow -Profile Any -Description "Connect to WireGuard relay" | Out-Null
Write-Host "  Out: WireGuard to ${RELAY_IP}:${RELAY_PORT}/udp" -ForegroundColor Green

# Outbound - DNS
New-NetFirewallRule -DisplayName "DNS: UDP 53" -Direction Outbound -Protocol UDP -RemotePort 53 -Action Allow -Profile Any | Out-Null
Write-Host "  Out: DNS 53/udp" -ForegroundColor Green

# Outbound - HTTP/HTTPS
New-NetFirewallRule -DisplayName "Web: HTTP" -Direction Outbound -Protocol TCP -RemotePort 80 -Action Allow -Profile Any | Out-Null
New-NetFirewallRule -DisplayName "Web: HTTPS" -Direction Outbound -Protocol TCP -RemotePort 443 -Action Allow -Profile Any | Out-Null
Write-Host "  Out: HTTP 80/tcp + HTTPS 443/tcp" -ForegroundColor Green

# Outbound - NTP
New-NetFirewallRule -DisplayName "System: NTP" -Direction Outbound -Protocol UDP -RemotePort 123 -Action Allow -Profile Any | Out-Null
Write-Host "  Out: NTP 123/udp" -ForegroundColor Green

# Step 4 - Model API validation
Write-Host "[4/5] Checking model API reachability..." -ForegroundColor Yellow
$APIS = @("api.deepseek.com","api.openai.com","api.anthropic.com","generativelanguage.googleapis.com","open.bigmodel.cn","api.moonshot.cn")
foreach ($api in $APIS) {
    try {
        $ip = [System.Net.Dns]::GetHostAddresses($api) | Select-Object -First 1
        Write-Host "  $api -> $($ip.IPAddressToString)" -ForegroundColor Gray
    } catch {
        Write-Host "  $api -> unresolved (proxy may handle this)" -ForegroundColor DarkYellow
    }
}

# Step 5 - Enable
Write-Host "[5/5] Enabling rules..." -ForegroundColor Yellow
Enable-NetFirewallRule -DisplayName "WG:*" -ErrorAction SilentlyContinue | Out-Null
Enable-NetFirewallRule -DisplayName "Web:*" -ErrorAction SilentlyContinue | Out-Null
Enable-NetFirewallRule -DisplayName "DNS:*" -ErrorAction SilentlyContinue | Out-Null
Enable-NetFirewallRule -DisplayName "System:*" -ErrorAction SilentlyContinue | Out-Null

Write-Host ""
Write-Host "========================================" -ForegroundColor Green
Write-Host "  Firewall whitelist ACTIVE" -ForegroundColor Green
Write-Host "========================================" -ForegroundColor Green
Write-Host ""
Write-Host 'Allowed:'
Write-Host "  In : WG ${WG_PORT}/udp + Tunnel ${TUNNEL} + Loopback"
Write-Host "  Out: WG relay ${RELAY_IP}:${RELAY_PORT}/udp + DNS 53/udp + HTTP/HTTPS 80,443/tcp + NTP 123/udp"
Write-Host ''
Write-Host 'BLOCKED: All other inbound/outbound connections'
Write-Host ''
Write-Host "Restore: netsh advfirewall import $backupFile" -ForegroundColor Yellow
