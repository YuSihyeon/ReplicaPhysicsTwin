#include "Misc/AutomationTest.h"
#include "Bridge/MuJoCoBridgeDemoActor.h"
#include "Bridge/MuJoCoBridgeTypes.h"

IMPLEMENT_SIMPLE_AUTOMATION_TEST(
	FMuJoCoBridgeMappingTest,
	"ReplicaPhysicsTwin.Bridge.MappingAndSequence",
	EAutomationTestFlags::EditorContext | EAutomationTestFlags::EngineFilter)

bool FMuJoCoBridgeMappingTest::RunTest(const FString& Parameters)
{
	FMuJoCoStateMessage Message;
	const FString JsonLine = TEXT("{\"type\":\"state\",\"schema_version\":1,\"seq\":8,\"sim_time\":0.5,\"units\":\"meter\",\"up_axis\":\"Z\",\"objects\":[{\"id\":\"test_box\",\"position_m\":[1.0,2.0,3.0],\"quaternion_wxyz\":[0.5,0.5,0.5,0.5],\"linear_velocity_mps\":[0.0,0.0,0.0],\"angular_velocity_rps\":[0.0,0.0,0.0]}]}\n");

	TestTrue(TEXT("state JSON parses"), FMuJoCoStateMessage::ParseLine(JsonLine, Message));
	TestEqual(TEXT("sequence is preserved"), Message.Seq, int64(8));
	TestEqual(TEXT("one object is present"), Message.Objects.Num(), 1);
	const FTransform UnrealTransform = Message.Objects[0].ToUnrealTransform();
	TestEqual(TEXT("meters convert to centimeters"), UnrealTransform.GetLocation(), FVector(100.0, 200.0, 300.0));
	TestTrue(TEXT("wxyz converts to Unreal xyzw quaternion"), UnrealTransform.GetRotation().Equals(FQuat(0.5, 0.5, 0.5, 0.5), 0.0001));
	TestTrue(TEXT("newer sequence applies"), FMuJoCoStateMessage::ShouldApplySequence(8, 9));
	TestFalse(TEXT("older sequence is ignored"), FMuJoCoStateMessage::ShouldApplySequence(8, 7));

	AMuJoCoBridgeDemoActor* DemoActor = NewObject<AMuJoCoBridgeDemoActor>();
	TestNotNull(TEXT("demo actor is constructible"), DemoActor);
	if (DemoActor != nullptr)
	{
		TestNotNull(TEXT("demo actor has a visual mesh"), DemoActor->GetVisualMesh());
		TestNotNull(TEXT("demo actor has a MuJoCo receiver"), DemoActor->GetReceiver());
		TestFalse(TEXT("demo mesh does not simulate Chaos physics"), DemoActor->GetVisualMesh()->IsSimulatingPhysics());
		TestEqual(TEXT("demo mesh collision is disabled"), DemoActor->GetVisualMesh()->GetCollisionEnabled(), ECollisionEnabled::NoCollision);
	}
	return true;
}
