{
  description = "A Nix flake for CT Log Benchmarks development environment";

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";
    flake-utils.url = "github:numtide/flake-utils";
  };

  outputs = { self, nixpkgs, flake-utils }:
    flake-utils.lib.eachDefaultSystem (system:
      let
        pkgs = import nixpkgs {
          inherit system;
          config.allowUnfree = true; # Required for terraform
        };
      in
      {
        devShells.default = pkgs.mkShell {
          buildInputs = with pkgs; [
            terraform
            google-cloud-sdk
            git
            gh
            go
            ko
          ];

          shellHook = ''
            echo "Welcome to the CT Log Benchmarks dev environment!"
            echo "Terraform version: $(terraform version | head -n1)"
            echo "GCloud version: $(gcloud --version | head -n1)"
            echo "Ko version: $(ko version)"
          '';
        };
      }
    );
}
