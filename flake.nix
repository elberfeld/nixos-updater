{
  description = "NixOS Updater – Tray-Tool für git-basierte NixOS-Konfigurationen";

  inputs.nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";

  outputs = { self, nixpkgs }:
    let
      systems = [ "x86_64-linux" "aarch64-linux" ];
      forAll = f: nixpkgs.lib.genAttrs systems (system: f nixpkgs.legacyPackages.${system});
    in
    {
      packages = forAll (pkgs: {
        default = pkgs.python3Packages.buildPythonApplication {
          pname = "nixos-updater";
          version = "0.1.0";
          pyproject = true;
          src = ./.;

          build-system = [ pkgs.python3Packages.setuptools ];
          dependencies = [ pkgs.python3Packages.pyqt6 ];
          nativeBuildInputs = [ pkgs.qt6.wrapQtAppsHook ];
          buildInputs = [ pkgs.qt6.qtbase pkgs.qt6.qtwayland ];

          dontWrapQtApps = true;
          preFixup = ''
            makeWrapperArgs+=("''${qtWrapperArgs[@]}" --prefix PATH : ${pkgs.lib.makeBinPath [ pkgs.git ]})
          '';

          postInstall = ''
            install -Dm644 nixos-updater.desktop $out/share/applications/nixos-updater.desktop
          '';

          meta.mainProgram = "nixos-updater";
        };
      });

      devShells = forAll (pkgs: {
        default = pkgs.mkShell {
          packages = [ (pkgs.python3.withPackages (ps: [ ps.pyqt6 ])) ];
        };
      });
    };
}
