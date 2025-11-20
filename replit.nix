{ pkgs }: {
  deps = [
    pkgs.python310Full
    pkgs.ffmpeg
    pkgs.curl
    pkgs.git
  ];
}
