#!/bin/zsh
# Uninstall the sandboxed macOS compatibility app for the current account.
emulate -L zsh
setopt NO_UNSET

if [[ $(/usr/bin/uname -s) != Darwin ]]; then
  print -u2 '此脚本仅适用于 macOS。'
  exit 1
fi

dry_run=0
if (( $# == 1 )) && [[ $1 == --dry-run ]]; then
  dry_run=1
elif (( $# != 0 )); then
  print -u2 '用法：卸载神将世界.command [--dry-run]'
  exit 2
fi

if (( EUID == 0 )) || [[ ${HOME:-} != /* || $HOME == / || ${HOME:A} == / ]]; then
  print -u2 '请在安装或登录游戏的 macOS 账户下直接运行，勿使用 sudo。'
  exit 1
fi

bundle_id=local.sjsj.compatibility
library="$HOME/Library"
failed=0
removed=0

if (( ! dry_run )) && /usr/bin/pgrep -u "$EUID" -x SJSJNative >/dev/null; then
  print -u2 '请先按 ⌘Q 完全退出《神将世界》，然后重新运行脚本。'
  exit 1
fi

remove_path() {
  local target=$1
  [[ -e "$target" || -L "$target" ]] || return 0
  if (( dry_run )); then
    print -r -- "将删除 $target"
  elif /bin/rm -rf -- "$target" && [[ ! -e "$target" && ! -L "$target" ]]; then
    print -r -- "已删除 $target"
    (( removed += 1 ))
  else
    print -ru2 -- "无法删除 $target"
    failed=1
  fi
}

typeset -a install_folders=(/Applications "$HOME/Applications")
typeset -a game_apps=()
for folder in "${install_folders[@]}"; do
  [[ -d "$folder" && ! -L "$folder" ]] || continue
  for app in "$folder"/*.app(N/); do
    [[ ! -L "$app" && -f "$app/Contents/Info.plist" ]] || continue
    installed_id=$(/usr/libexec/PlistBuddy -c 'Print CFBundleIdentifier' "$app/Contents/Info.plist" 2>/dev/null)
    [[ "$installed_id" == "$bundle_id" ]] || continue
    executable=$(/usr/libexec/PlistBuddy -c 'Print CFBundleExecutable' "$app/Contents/Info.plist" 2>/dev/null)
    [[ "$executable" == SJSJNative ]] || continue
    game_apps+=("$app")
  done
done

for app in "${game_apps[@]}"; do
  remove_path "$app"
done

if /usr/bin/defaults read "$bundle_id" >/dev/null 2>&1; then
  if (( dry_run )); then
    print -r -- "将清除偏好设置 $bundle_id"
  elif ! /usr/bin/defaults delete "$bundle_id"; then
    print -ru2 -- "无法清除偏好设置 $bundle_id"
    failed=1
  fi
fi

# Use exact bundle paths. rm does not follow symlinks inside the sandbox container.
for area in Containers WebKit Caches 'Application Support' Preferences HTTPStorages Cookies 'Saved Application State'; do
  if [[ -L "$library" || -L "$library/$area" ]]; then
    print -ru2 -- "跳过指向其他位置的目录 $library/$area"
    failed=1
    continue
  fi
  case "$area" in
    Preferences) remove_path "$library/$area/$bundle_id.plist" ;;
    'Saved Application State') remove_path "$library/$area/$bundle_id.savedState" ;;
    *) remove_path "$library/$area/$bundle_id" ;;
  esac
  if [[ "$area" == Cookies || "$area" == HTTPStorages ]]; then
    remove_path "$library/$area/$bundle_id.binarycookies"
  fi
  if [[ "$area" == Caches ]]; then
    # Some earlier bridge builds stored the same project's public asset cache here.
    remove_path "$library/$area/SJSJPublicAssets"
  fi
done

for key in DARWIN_USER_CACHE_DIR DARWIN_USER_TEMP_DIR; do
  directory=$(/usr/bin/getconf "$key" 2>/dev/null) || continue
  directory=${directory%/}
  [[ "$directory" == /var/folders/* || "$directory" == /private/var/folders/* ]] || continue
  remove_path "$directory/$bundle_id"
  for entry in "$directory"/com.apple.WebKit.*+"$bundle_id"(N); do
    remove_path "$entry"
  done
done

if (( failed )); then
  print -u2 '卸载未完成。若 App 因权限无法删除，请在 Finder 中移除；若沙盒数据受系统保护，请允许终端访问该 App 的数据后再运行。'
  exit 1
fi
if (( dry_run )); then
  print '预览结束。'
elif (( removed )); then
  print '已清理兼容工具及当前账户的本地登录数据、设置和缓存。'
else
  print '没有找到仍需清理的兼容工具文件。'
fi
