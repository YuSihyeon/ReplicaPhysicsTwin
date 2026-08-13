#pragma once

#include "CoreMinimal.h"
#include "Components/ActorComponent.h"
#include "Dom/JsonObject.h"
#include "Bridge/MuJoCoBridgeTypes.h"
#include "MuJoCoStateReceiverComponent.generated.h"

class FSocket;

DECLARE_LOG_CATEGORY_EXTERN(LogMuJoCoBridge, Log, All);

/**
 * Receives MuJoCo-authoritative state and applies it to the owning Actor.
 * This component never simulates or integrates physics in Unreal.
 */
UCLASS(ClassGroup = (Bridge), meta = (BlueprintSpawnableComponent))
class REPLICAPHYSICSTWIN_API UMuJoCoStateReceiverComponent : public UActorComponent
{
	GENERATED_BODY()

public:
	UMuJoCoStateReceiverComponent();

	virtual void BeginPlay() override;
	virtual void EndPlay(const EEndPlayReason::Type EndPlayReason) override;
	virtual void TickComponent(float DeltaTime, ELevelTick TickType, FActorComponentTickFunction* ThisTickFunction) override;

	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "MuJoCo Bridge")
	FString ObjectId = TEXT("test_box");

	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "MuJoCo Bridge")
	FString Host = TEXT("127.0.0.1");

	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "MuJoCo Bridge")
	int32 Port = 7007;

	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "MuJoCo Bridge")
	float ReconnectIntervalSeconds = 0.5f;

	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "MuJoCo Bridge")
	bool bAutoConnect = true;

	UFUNCTION(BlueprintCallable, Category = "MuJoCo Bridge")
	bool SendApplyImpulse(FVector ImpulseNs);

	bool SendApplyImpulseForObject(const FString& InObjectId, FVector ImpulseNs);

	UFUNCTION(BlueprintCallable, Category = "MuJoCo Bridge")
	bool SendReset();

	UFUNCTION(BlueprintCallable, Category = "MuJoCo Bridge")
	bool SendPause(bool bPaused);

	UFUNCTION(BlueprintCallable, Category = "MuJoCo Bridge")
	bool SendLiftDrop(float LiftHeightM = 0.30f);

	bool SendLiftDropForObject(const FString& InObjectId, float LiftHeightM = 0.30f);

	bool SendGrabBegin(const TArray<FString>& ObjectIds, FVector AnchorM, FString& OutGrabId);
	bool SendGrabUpdate(const FString& GrabId, FVector TargetPositionM, const FQuat& TargetRotation = FQuat::Identity);
	bool SendGrabEnd(const FString& GrabId);

	UFUNCTION(BlueprintCallable, Category = "MuJoCo Bridge")
	bool IsConnected() const { return Socket != nullptr; }

	int64 GetLastAppliedSequence() const { return LastAppliedSeq; }
	const FMuJoCoStateMessage& GetLatestState() const { return LatestState; }

private:
	FSocket* Socket = nullptr;
	TArray<uint8> ReceiveBuffer;
	int64 LastAppliedSeq = -1;
	double NextReconnectTime = 0.0;
	FMuJoCoStateMessage LatestState;

	bool TryConnect();
	void CloseSocket(const TCHAR* Reason);
	void ReadAvailable();
	void ProcessLine(const FString& Line);
	void ApplyState(const FMuJoCoStateMessage& Message);
	bool SendCommand(const TSharedRef<FJsonObject>& Command);
	void ScheduleReconnect();
};
