#!/bin/sh
# install.sh [--no-modify-path]
set -eu
R=Luaxite/Luaxite-rs N=luaxite D= M=1 O=0 W=0 T=0 E= MB="# >>> luaxite >>>" ME="# <<< luaxite <<<"
d(){ printf 'error: %s\n' "$*" >&2;exit 1;}
h(){ command -v "$1" >/dev/null 2>&1;}
for i;do case $i in --no-modify-path)M=0;;-h|--help)sed -n 2p "$0";exit;;*)d "unknown option: $i";;esac;done
U=$(uname -s);A=$(uname -m)
{ [ -n "${TERMUX_VERSION:-}" ]||[ "$(uname -o 2>/dev/null)" = Android ];}&&T=1
case $U in MINGW*|MSYS*|CYGWIN*)W=1;E=.exe;;esac
case $A in x86_64|amd64)a=x86_64;;aarch64|arm64|armv8b)a=aarch64;;armv7*|armv6*|armv8l|arm)a=armv7;;*)a=;;esac
tgt(){
[ -n "$a" ]||d "unsupported CPU: $A"
[ "$a" = armv7 ]&&d "32-bit ARM ($A) is not supported (a dependency, simdnbt, is 64-bit only)"
if [ $T = 1 ];then echo $a-linux-android;return;fi
case $U in
Linux)echo $a-unknown-linux-musl;;
Darwin)[ "$(sysctl -n sysctl.proc_translated 2>/dev/null||echo 0)" = 1 ]&&a=aarch64;echo $a-apple-darwin;;
MINGW*|MSYS*|CYGWIN*)echo $a-pc-windows-msvc;;
*)d "unsupported OS: $U";;esac;}
rel(){ echo https://github.com/$R/releases/latest/download/$1.zip;}
f(){ if h curl;then curl -fsSL --retry 2 -o "$2" "$1";elif h wget;then wget -q -O "$2" "$1";else d "need curl or wget";fi;}
P=$(mktemp -d);trap 'rm -rf "$P"' EXIT INT TERM
t=$(tgt);u=$(rel $t);f "$u" "$P/p"||d "download failed: $u"
Z=$P/p
if [ -d "$Z" ]||[ "$(head -c2 "$Z")" = PK ];then
s=$Z;if [ ! -d "$Z" ];then s=$P/x;mkdir "$s"
if h unzip;then unzip -q -o "$Z" -d "$s";elif h bsdtar;then bsdtar -xf "$Z" -C "$s";elif h python3||h python;then y=python3;h $y||y=python;$y -c 'import sys,zipfile;zipfile.ZipFile(sys.argv[1]).extractall(sys.argv[2])' "$Z" "$s";elif h tar;then tar -xf "$Z" -C "$s";else d "need unzip";fi;fi
Z=$(find "$s" -type f \( -name $N -o -name $N.exe \)|head -n1);[ -n "$Z" ]||d "no $N in payload";fi
if [ $T = 1 ]&&[ -n "${PREFIX:-}" ];then D=$PREFIX/bin;O=1
else e=$(command -v $N 2>/dev/null||true);case $e in /*)q=$(dirname "$e");[ -w "$q" ]&&D=$q&&O=1;;esac;D=${D:-$HOME/.local/bin};fi
mkdir -p "$D"&&[ -w "$D" ]||d "cannot write $D"
X=$D/$N$E;t=$D/.$N.$$
cp "$Z" "$t"&&chmod 755 "$t"&&mv -f "$t" "$X"
[ $U = Darwin ]&&xattr -d com.apple.quarantine "$X" 2>/dev/null||true
if [ $T = 1 ]&&[ -n "${PREFIX:-}" ];then
h patchelf||{ h pkg&&pkg install -y patchelf >/dev/null 2>&1||true;}
if h patchelf&&patchelf --print-needed "$X" 2>/dev/null|grep -q 'libc++_shared';then
[ -e "$PREFIX/lib/libc++_shared.so" ]||{ h pkg&&pkg install -y libc++ >/dev/null 2>&1||true;}
patchelf --add-rpath "$PREFIX/lib" "$X" 2>/dev/null||patchelf --set-rpath "$PREFIX/lib" "$X"||echo "warning: could not point $X at $PREFIX/lib; run it as: LD_LIBRARY_PATH=$PREFIX/lib $N" >&2
fi;fi
"$X" --help >/dev/null 2>&1||echo "warning: $X did not run" >&2
echo "installed: $X"
ub(){ mkdir -p "$(dirname "$1")";[ -e "$1" ]||:>"$1";g=$(mktemp);awk -v s="$MB" -v e="$ME" '$0==s{k=1;next}$0==e{k=0;next}!k' "$1">"$g";printf '%s\n' "$2">>"$g";cat "$g">"$1";rm -f "$g";echo "PATH: updated $1";}
if [ $M = 1 ]&&[ $O = 0 ];then
if [ $W = 1 ];then
if h powershell.exe;then w=$D;h cygpath&&w=$(cygpath -w "$D");LUAXITE_DIR=$w powershell.exe -NoProfile -NonInteractive -Command '$d=$env:LUAXITE_DIR;$p=[Environment]::GetEnvironmentVariable("Path","User");if(-not $p){$p=""};$q=@($p -split ";"|Where-Object{$_ -ne ""});if($q -notcontains $d){[Environment]::SetEnvironmentVariable("Path",(($q+$d) -join ";"),"User")}' >/dev/null;else echo "add $D to your user PATH by hand" >&2;fi
else
case $D in "$HOME")r='$HOME';;"$HOME"/*)r='$HOME'"${D#"$HOME"}";;*)r=$D;;esac
b="$MB
case \":\$PATH:\" in *\":$r:\"*) ;; *) export PATH=\"$r:\$PATH\" ;; esac
$ME"
ub "$HOME/.profile" "$b"
[ -f "$HOME/.bash_profile" ]&&ub "$HOME/.bash_profile" "$b"
{ h bash||[ -f "$HOME/.bashrc" ];}&&ub "$HOME/.bashrc" "$b"
{ h zsh||[ -f "$HOME/.zshrc" ]||[ $U = Darwin ];}&&ub "$HOME/.zshrc" "$b"
g=${XDG_CONFIG_HOME:-$HOME/.config}/fish
{ h fish||[ -d "$g" ];}&&ub "$g/config.fish" "$MB
if not contains -- \"$r\" \$PATH
    set -gx PATH \"$r\" \$PATH
end
$ME"
fi;fi
case ":$PATH:" in *":$D:"*)echo "done: run $N";;*)echo "done: open a new terminal (or export PATH=\"$D:\$PATH\"), then run $N";;esac
