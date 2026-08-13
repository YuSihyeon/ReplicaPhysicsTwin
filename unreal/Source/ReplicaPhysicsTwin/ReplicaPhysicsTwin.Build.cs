using UnrealBuildTool;

public class ReplicaPhysicsTwin : ModuleRules
{
	public ReplicaPhysicsTwin(ReadOnlyTargetRules Target) : base(Target)
	{
		PCHUsage = PCHUsageMode.UseExplicitOrSharedPCHs;

		PublicDependencyModuleNames.AddRange(new string[]
		{
			"Core",
			"CoreUObject",
			"Engine",
			"InputCore",
			"Json",
			"JsonUtilities",
			"Sockets",
			"Networking",
			"ProceduralMeshComponent"
		});
	}
}
