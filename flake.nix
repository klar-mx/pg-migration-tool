{
  inputs = { nixpkgs.url = "github:nixos/nixpkgs/nixpkgs-unstable"; };

  outputs = { self, nixpkgs, ... }@inputs:
    let
      system = "x86_64-linux";
      pkgs = import nixpkgs { inherit system; };
      pythonPackage = pkgs.python311;
      myPython = (pythonPackage.withPackages (ps: with ps; [ pip ]));
    in {
      devShells.${system}.default = pkgs.mkShell {
        buildInputs = with pkgs; [
          myPython
          (poetry.override { python3 = pythonPackage; })
        ];
      };
    };
}
