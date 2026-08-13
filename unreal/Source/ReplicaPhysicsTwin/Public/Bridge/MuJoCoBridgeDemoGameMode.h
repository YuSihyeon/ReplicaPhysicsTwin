#pragma once

#include "CoreMinimal.h"
#include "GameFramework/GameModeBase.h"
#include "MuJoCoBridgeDemoGameMode.generated.h"

/** Spawns a deterministic Phase 3 visual-only test scene at BeginPlay. */
UCLASS()
class REPLICAPHYSICSTWIN_API AMuJoCoBridgeDemoGameMode : public AGameModeBase
{
	GENERATED_BODY()

public:
	AMuJoCoBridgeDemoGameMode();

	virtual void BeginPlay() override;
};
