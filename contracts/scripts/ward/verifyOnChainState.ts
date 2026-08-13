import { ethers } from "hardhat";

async function main() {
  const ATTESTOR_ADDRESS = "0xD06059f36cB6fc2737977f1445c95713f6a85b0F";
  const GUARDIAN_ADDRESS = "0x5FCDc267ca392B64362957b7FD021719466d1775";

  const attestor = await ethers.getContractAt("WardAttestor", ATTESTOR_ADDRESS);
  const guardian = await ethers.getContractAt("Guardian", GUARDIAN_ADDRESS);

  const requiredConfig = await attestor.requiredConfig();
  const currentSigner = await guardian.wardSigner();

  console.log("Attestor required image digest:", ethers.hexlify(requiredConfig.imageDigest));
  console.log("Guardian current signer:       ", currentSigner);
}

main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
