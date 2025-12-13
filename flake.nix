{
  inputs = {
    nixpkgs.url = "github:nixos/nixpkgs/nixpkgs-unstable";
    flake-utils = {
      url = "github:numtide/flake-utils";
    };
  };

  outputs =
    {
      self,
      nixpkgs,
      flake-utils,
      ...
    }@inputs:
    flake-utils.lib.eachDefaultSystem (
      system:
      let
        pkgs = import nixpkgs {
          inherit system;
        };
        myPython = (
          pkgs.python311.withPackages (
            ps: with ps; [
              openai-whisper
              pyaudio
              playsound
              pynput
              dbus-python
              # pydbus
              plyer
              termcolor
              (buildPythonPackage rec {
                pname = "beepy";
                version = "1.0.9";
                format = "setuptools";
                src = fetchPypi {
                  inherit pname version;
                  sha256 = "sha256-BbLWeJq7Q5MAaeHZalbJ6LBJg3jgl4TP6aHewCNo/Ks=";
                };
                doCheck = false;
                # Fix for missing README.md in source distribution
                prePatch = ''
                  touch README.md
                '';
                propagatedBuildInputs = [
                  ps.simpleaudio
                ];
              })
            ]
          )
        );
        dependencies = [
          myPython
          pkgs.alsa-plugins
          pkgs.pulseaudio
        ];
      in
      rec {
        defaultApp = apps.whisper-input;

        apps.whisper-input = {
          type = "app";
          program = "${defaultPackage}/bin/whisper-input";
        };

        devShells.default = pkgs.mkShell {
          buildInputs = [ dependencies ];
        };

        defaultPackage = pkgs.stdenv.mkDerivation {
          name = "defaultPackage";
          buildInputs = dependencies;
          src = ./src;
          dontBuild = true;
          installPhase = ''
                        mkdir -p $out/bin
                        cp -r . $out
                        # add a `whisper-input` script, which just calls `python3 whisper-input.py`
                        # Set ALSA_PLUGIN_DIR and LD_LIBRARY_PATH so ALSA can find the PulseAudio plugins
                        cat > $out/bin/whisper-input <<EOF
            #!${pkgs.stdenv.shell}
            export ALSA_PLUGIN_DIR="${pkgs.alsa-plugins}/lib/alsa-lib"
            export LD_LIBRARY_PATH="${pkgs.alsa-plugins}/lib:${pkgs.pulseaudio}/lib:\''${LD_LIBRARY_PATH:-}"
            ${myPython}/bin/python3 $out/whisper-input.py "\$@"
            EOF
                        chmod +x $out/bin/whisper-input
          '';
        };
      }
    );
}
