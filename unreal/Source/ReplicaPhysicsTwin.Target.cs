using UnrealBuildTool;

public class ReplicaPhysicsTwinTarget : TargetRules
{
	public ReplicaPhysicsTwinTarget(TargetInfo Target) : base(Target)
	{
		Type = TargetType.Game;
		DefaultBuildSettings = BuildSettingsVersion.V6;
		IncludeOrderVersion = EngineIncludeOrderVersion.Unreal5_7;
		ExtraModuleNames.Add("ReplicaPhysicsTwin");
	}
}
