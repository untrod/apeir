<#
.SYNOPSIS
  保护指挥层终端的敏感文件 —— 只允许当前用户读取,拒绝其他用户/进程访问。
  为什么需要:config.py 含令牌/密钥,sessions.json 含对话历史,transcript 含命令记录。
  即使恶意软件入侵,也无法读取这些文件(ACL 级保护)。
  用法: 管理员 PowerShell 运行此脚本。
#>
#Requires -RunAsAdministrator

$root = $PSScriptRoot
$files = @(
    "$root\config.py",
    "$root\sessions.json",
    "$root\brain.log",
    "$root\agent.log",
    "$root\crypto.py"
)

$dirs = @(
    "$root\sessions"  # transcript 目录
)

Write-Host "锁定敏感文件..." -ForegroundColor Yellow

$files | ForEach-Object {
    if (Test-Path $_) {
        # 获取当前 ACL
        $acl = Get-Acl $_
        # 禁用继承
        $acl.SetAccessRuleProtection($true, $false)
        # 清除所有非管理员/非当前用户权限
        $acl.Access | ForEach-Object {
            if ($_.IdentityReference -notmatch "Administrator|SYSTEM|$env:USERNAME") {
                $acl.RemoveAccessRule($_) | Out-Null
            }
        }
        # 设置只读
        Set-ItemProperty $_ -Name IsReadOnly -Value $true
        Write-Host "  已锁定: $_" -ForegroundColor Green
    } else {
        Write-Host "  跳过(不存在): $_" -ForegroundColor Gray
    }
}

$dirs | ForEach-Object {
    if (Test-Path $_) {
        $acl = Get-Acl $_
        $acl.SetAccessRuleProtection($true, $false)
        Set-Acl $_ $acl
        Write-Host "  已锁定目录: $_" -ForegroundColor Green
    }
}

Write-Host ""
Write-Host "敏感文件已锁定! 只有 $env:USERNAME 和 SYSTEM 可读。" -ForegroundColor Green
Write-Host "编辑 config.py 前需先取消只读: attrib -r config.py" -ForegroundColor Yellow
