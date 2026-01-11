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
    }:
    flake-utils.lib.eachDefaultSystem (
      system:
      let
        pkgs = import nixpkgs {
          inherit system;
          config = {
            # Disable tests for Python packages to prevent resource-intensive builds
            # This is especially important for heavy packages like PyTorch
            doCheckByDefault = false;
          };
        };
        # Override Python to disable tests for heavy packages
        # This prevents resource-intensive test suites (especially PyTorch) from running
        python311NoTests = pkgs.python311.override {
          packageOverrides = python-final: python-prev: {
            # Disable tests for the heaviest packages
            torch = python-prev.torch.overridePythonAttrs (old: {
              doCheck = false;
            });
            openai-whisper = python-prev.openai-whisper.overridePythonAttrs (old: {
              doCheck = false;
            });
            # Disable tests for other potentially heavy packages
            numpy = python-prev.numpy.overridePythonAttrs (old: {
              doCheck = false;
            });
            scipy = python-prev.scipy.overridePythonAttrs (old: {
              doCheck = false;
            });
          };
        };
        myPython = (
          python311NoTests.withPackages (
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
        defaultPackage = pkgs.stdenv.mkDerivation {
          name = "whisper-input";
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
      in
      {
        packages.default = defaultPackage;

        apps.default = {
          type = "app";
          program = "${defaultPackage}/bin/whisper-input";
        };

        apps.whisper-input = {
          type = "app";
          program = "${defaultPackage}/bin/whisper-input";
        };

        devShells.default = pkgs.mkShell {
          buildInputs = dependencies;
        };
      }
    );
}
